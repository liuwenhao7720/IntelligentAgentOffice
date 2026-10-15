# -*- coding: utf-8 -*-
"""主动贡献知识库专项测试（上传文件 / 在线填写 / 自动总结 → 简道云知识库表单）。

直接运行：python tests/test_knowledge.py
- 进程内 TestClient + 独立临时 SQLite，全程无真实网络（monkeypatch 简道云写侧）
- 覆盖：知识库字段映射（对照表单 68ad15ab88c411d76390e0a2）、payload 转换、
  部门 dept_no 解析与降级、附件上传降级、三种贡献方式、本地镜像可见可搜、权限
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="vflo_kb_test_"))
os.environ["MOCK_LLM"] = "1"   # LLM mock：draft 走规则兜底提取
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["DEV_ADMIN_USERS"] = "管理员甲"
# 假凭证使 jdy.mock=False；push_form/upload_file/list_departments 会被 monkeypatch
os.environ["JDY_APP_ID"] = "fake-app"
os.environ["JDY_API_KEY"] = "fake-key"
os.environ["JDY_ENTRY_TASK"] = "entry-task-1"
os.environ["JDY_ENTRY_KNOWLEDGE"] = "68ad15ab88c411d76390e0a2"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.jdy import (  # noqa: E402
    KNOWLEDGE_LABEL_TO_WIDGET, PushResult, build_jdy_knowledge, jdy,
    to_widget_payload,
)
from app.services import knowledge as kb  # noqa: E402

FAILED: list[str] = []

# 线上表单实测字段（widget/list 2026-10-14 核对）
W = KNOWLEDGE_LABEL_TO_WIDGET


def check(name: str, cond: bool, detail: object = "") -> None:
    if cond:
        print(f"  ok  {name}")
    else:
        FAILED.append(name)
        print(f" FAIL {name} :: {detail}")


def login(client: TestClient, name: str, dept: str = "项目部", role: str = "staff") -> dict:
    r = client.post("/api/v1/auth/dev-login",
                    json={"name": name, "department": dept, "position": "工程师", "role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# 写侧桩：记录 push 内容，不回真网
_PUSHED: list[dict] = []
_UPLOAD_FAIL = {"on": False}


def fake_push_form(entry_id, data, note=""):
    _PUSHED.append({"entry_id": entry_id, "data": dict(data), "note": note})
    return PushResult(ok=True, mode="live", entry_id=f"kb-{len(_PUSHED):04d}",
                      message="fake", raw={})


def fake_upload_file(entry_id, filename, content, mime=""):
    if _UPLOAD_FAIL["on"]:
        return PushResult(ok=False, mode="live", message="APIKey 无文件上传权限（HTTP 403）")
    return PushResult(ok=True, mode="live", entry_id=f"ftoken-{filename}", raw={})


def fake_list_departments():
    return {"项目部": 5, "商务部": 4, "威标部": 12}


def main() -> int:
    print("[map] 字段映射（对照知识库表单 68ad15ab88c411d76390e0a2）")
    expect = {
        "客户": "_widget_1756173740163", "项目": "_widget_1756173740164",
        "问题": "_widget_1756173740165", "回答": "_widget_1768902936664",
        "附件": "_widget_1767494919162", "备注": "_widget_1756173740167",
        "国家": "_widget_1756173740168", "部门": "_widget_1756196363918",
    }
    check("8 个字段映射与线上一致", W == expect, W)

    p = to_widget_payload(build_jdy_knowledge(
        question="机械密封金属面是否必须", answer="非金属面即可，详见澄清",
        customer="MTO", project="S1240058", country="乌兹别克斯坦(Uzbekistan)",
        remark="澄清函", dept=5))
    check("问题 widget 值", p[W["问题"]]["value"].startswith("机械密封"), p)
    check("回答 widget 值", p[W["回答"]]["value"].startswith("非金属面"), p)
    check("客户/项目/国家/备注 widget 齐",
          all(k in p for k in (W["客户"], W["项目"], W["国家"], W["备注"])), list(p))
    check("部门 dept_no 数字透传", p[W["部门"]]["value"] == 5, p)
    # 部门名称（未解析）不写入，避免简道云校验报错
    p2 = to_widget_payload(build_jdy_knowledge(question="q", answer="a", dept="项目部"))
    check("部门名称不直接写入控件", W["部门"] not in p2, p2)
    # 附件结构校验
    p3 = to_widget_payload(build_jdy_knowledge(question="q", answer="a",
                                               attachments=[{"fileToken": "t1", "name": "f.txt"}]))
    check("附件 fileToken 结构透传", p3[W["附件"]]["value"][0]["fileToken"] == "t1", p3)
    p4 = to_widget_payload(build_jdy_knowledge(question="q", answer="a", attachments=["f.txt"]))
    check("非法附件结构被丢弃", W["附件"] not in p4, p4)
    # 任务表映射回归（合并映射后互不干扰）
    pt = to_widget_payload({"任务名称": "周报", "开始时间": "2026-10-14"})
    check("任务映射不受影响", pt["_widget_1668082756215"]["value"] == "周报"
          and pt["_widget_1667894235099"]["value"].endswith("T00:00:00.000Z"), pt)

    # 装桩
    jdy.push_form = fake_push_form            # type: ignore[assignment]
    jdy.upload_file = fake_upload_file        # type: ignore[assignment]
    jdy.list_departments = fake_list_departments  # type: ignore[assignment]
    kb._DEPT_CACHE.update(at=0.0, map={})     # 清缓存确保走桩
    assert not jdy.mock

    with TestClient(app) as client:
        h = login(client, "员工乙", dept="项目部")
        h_admin = login(client, "管理员甲", role="admin")

        print("[fields] 表单字段定义")
        r = client.get("/api/v1/knowledge/fields", headers=h)
        check("fields 200", r.status_code == 200, r.text)
        d = r.json()
        keys = [f["key"] for f in d["fields"]]
        check("字段键齐", keys == ["question", "answer", "customer", "project", "country", "remark"], keys)
        check("必填标记", [f["key"] for f in d["fields"] if f["required"]] == ["question", "answer"], d["fields"])
        check("部门清单来自通讯录", d["departments"] == ["商务部", "威标部", "项目部"], d["departments"])
        check("默认部门=登录部门", d["default_department"] == "项目部", d)
        r = client.get("/api/v1/knowledge/fields")
        check("未登录 401", r.status_code == 401, r.status_code)

        print("[contribute] 在线填写 → 推送简道云 + 本地镜像")
        r = client.post("/api/v1/knowledge/contribute", headers=h, json={
            "question": "轴承座冷却系统是否必须配置",
            "answer": "介质温度 50℃ 以下可不配冷却系统，详见技术澄清记录。",
            "customer": "Enter Engineering", "project": "56 038",
            "country": "乌兹别克斯坦(Uzbekistan)", "remark": "技术澄清",
        })
        check("提交 200", r.status_code == 200, r.text)
        d = r.json()
        check("live 推送成功", d["ok"] and d["mode"] == "live" and d["data_id"] == "kb-0001", d)
        check("部门已解析写入", d["dept_written"] is True, d)
        check("本地镜像已建", d["mirrored"] is True, d)
        sent = _PUSHED[-1]["data"]
        check("推送字段=中文标签", sent["问题"].startswith("轴承座") and sent["客户"] == "Enter Engineering", sent)
        check("推送部门=dept_no 5", sent["部门"] == 5, sent)

        # 镜像可读可搜
        r = client.get("/api/v1/jdy/data/knowledge", headers=h)
        items = r.json()["items"]
        check("镜像列表可见", any(x["data_id"] == "kb-0001" for x in items), items)
        rec = next(x for x in items if x["data_id"] == "kb-0001")
        check("镜像标题=问题", rec["title"].startswith("轴承座冷却"), rec)
        check("镜像部门投影", rec["dept"] == "项目部", rec)
        r = client.get("/api/v1/jdy/data/knowledge?q=轴承座", headers=h)
        check("镜像可搜索", r.json()["total"] == 1, r.json())
        r = client.get("/api/v1/jdy/data/knowledge/kb-0001", headers=h)
        f = r.json()["fields"]
        check("镜像详情中文字段", f.get("问题", "").startswith("轴承座") and f.get("回答", "").startswith("介质温度"), f)
        check("镜像创建人=贡献者", f.get("创建人") == "员工乙", f)

        print("[contribute] 必填校验与部门降级")
        r = client.post("/api/v1/knowledge/contribute", headers=h,
                        json={"question": "", "answer": "x"})
        check("缺问题 422", r.status_code == 422, r.status_code)
        r = client.post("/api/v1/knowledge/contribute", headers=h_admin, json={
            "question": "未知部门测试问题", "answer": "答案", "department": "不存在部",
        })
        d = r.json()
        check("未知部门降级：不写控件、并入备注",
              d["ok"] and d["dept_written"] is False and "不存在部" in _PUSHED[-1]["data"]["备注"],
              {"resp": d, "sent": _PUSHED[-1]["data"]})

        print("[upload] 上传文件 → AI 起草 → 提交（含附件）")
        files = [("files", ("澄清纪要.txt", "客户 MTO 在 S1240058 项目澄清会上提出：机械密封备件是否要求金属面。"
                                          "我方答复：密封动静环均为非金属面，金属面不适用（NA）。", "text/plain"))]
        r = client.post("/api/v1/chat/uploads", headers=h,
                        files=files)
        check("上传 200", r.status_code == 200, r.text)
        att = r.json()[0]
        check("解析成功", att["extract_status"] == "ok" and att["text_len"] > 10, att)

        r = client.post("/api/v1/knowledge/draft", headers=h, json={"attachment_ids": [att["id"]]})
        check("文件起草 200", r.status_code == 200, r.text)
        d = r.json()
        check("草稿问题非空", bool(d["draft"]["question"]), d["draft"])
        check("草稿回答含素材", "机械密封" in d["draft"]["answer"], d["draft"])
        check("备注含来源文件", "澄清纪要.txt" in d["draft"]["remark"], d["draft"])
        check("mock_llm 标记", d["mock_llm"] is True, d)

        r = client.post("/api/v1/knowledge/contribute", headers=h, json={
            **d["draft"], "attachment_ids": [att["id"]], "push_attachments": True,
        })
        d2 = r.json()
        check("带附件提交 200", r.status_code == 200, d2)
        check("附件已传 1 个", d2["attachments_pushed"] == 1, d2)
        check("附件 fileToken 进入 payload",
              _PUSHED[-1]["data"]["附件"][0]["fileToken"] == "ftoken-澄清纪要.txt", _PUSHED[-1]["data"])

        # 附件上传失败（403）降级：文件名写入备注
        _UPLOAD_FAIL["on"] = True
        files = [("files", ("无权限附件.txt", "测试内容：附件上传权限未开通时的降级。", "text/plain"))]
        att2 = client.post("/api/v1/chat/uploads", headers=h, files=files).json()[0]
        r = client.post("/api/v1/knowledge/contribute", headers=h, json={
            "question": "附件降级验证", "answer": "403 时文件名写入备注。",
            "attachment_ids": [att2["id"]], "push_attachments": True,
        })
        d3 = r.json()
        check("403 降级提交仍成功", d3["ok"] is True, d3)
        check("附件失败清单", d3["attachments_failed"] == ["无权限附件.txt"], d3)
        check("文件名并入备注", "无权限附件.txt" in _PUSHED[-1]["data"]["备注"], _PUSHED[-1]["data"])
        check("附件字段为空列表", _PUSHED[-1]["data"]["附件"] == [], _PUSHED[-1]["data"])
        _UPLOAD_FAIL["on"] = False

        print("[summarize] 自动总结起草")
        r = client.post("/api/v1/knowledge/draft", headers=h, json={
            "text": "客户 Enter Engineering 澄清：所有温度元件都需配 4-20mA 信号变送器。\n"
                    "答复：泵用温度/振动变送器已配 4-20mA；电机温度元件未配，如需变更请告知。",
        })
        d = r.json()
        check("总结起草 200", r.status_code == 200, r.text)
        check("总结草稿结构齐", set(d["draft"]) == {"question", "answer", "customer", "project", "country", "remark"}, d["draft"])
        check("总结回答含素材", "4-20mA" in d["draft"]["answer"], d["draft"])
        r = client.post("/api/v1/knowledge/draft", headers=h, json={})
        check("空起草 422", r.status_code == 422, r.status_code)

        # 文本+文件混合起草
        r = client.post("/api/v1/knowledge/draft", headers=h,
                        json={"text": "电机轴承温度高报警值 90℃。", "attachment_ids": [att["id"]]})
        check("混合起草 200", r.status_code == 200, r.text)

        print("[mirror] 镜像与全量同步同构（poller 覆盖更新不报错）")
        from app.database import SessionLocal
        from app.services import jdy_sync
        _real_query = jdy.query_form if hasattr(jdy, "query_form") else None
        # 模拟 poller 拉取到同一条（同 data_id）：应更新而非新增
        jdy.query_form = lambda entry_id, **kw: ([{  # type: ignore[assignment]
            "_id": "kb-0001",
            W["问题"]: "轴承座冷却系统是否必须配置（简道云端编辑）",
            W["回答"]: "介质温度 50℃ 以下可不配。",
            W["客户"]: "Enter Engineering",
            W["部门"]: None,
            "creator": {"name": "员工乙"},
            "createTime": "2026-10-14T09:00:00.000Z",
        }] if entry_id == "68ad15ab88c411d76390e0a2" else [])
        jdy.list_widgets = lambda entry_id: {  # type: ignore[assignment]
            v: k for k, v in KNOWLEDGE_LABEL_TO_WIDGET.items()}
        db = SessionLocal()
        try:
            res = jdy_sync.sync_entry(db, "knowledge")
        finally:
            db.close()
        check("poller 同步成功", res["status"] == "success", res)
        check("同 id 更新而非新增", res["updated"] == 1 and res["created"] == 0, res)
        r = client.get("/api/v1/jdy/data/knowledge/kb-0001", headers=h)
        check("poller 更新生效", r.json()["fields"]["问题"].endswith("（简道云端编辑）"), r.json()["fields"])
        if _real_query:
            jdy.query_form = _real_query  # type: ignore[assignment]

    if FAILED:
        print(f"\nTEST_KNOWLEDGE FAILED: {len(FAILED)} 项 -> {FAILED}")
        return 1
    print("\nTEST_KNOWLEDGE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
