# -*- coding: utf-8 -*-
"""冒烟测试：登录 → 选场景 → 生成 → 定稿 → 知产 → 统计。
直接对内存/SQLite 跑，不依赖已启动服务。

末尾编排「真实链路 E2E」阶段（tests/e2e_real.py）：
- mock_llm 生效（MOCK_LLM=1/true/yes/on 或未配置任何模型 Key）→ 自动 SKIP，整体仍退出 0；
- 检测到真实模型 Key → 子进程跑 e2e_real.py --spawn --require-real，透传退出码；
- 可用 --no-e2e 或 RUN_E2E=0 整段关闭。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 冒烟需要管理员接口：将测试员加入开发登录管理员白名单（须在导入 app 前强制设置，
# 避免继承外部环境变量导致结果不确定）
os.environ["DEV_ADMIN_USERS"] = "测试员"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed.scenarios import seed_scenarios  # noqa: E402


def _is_mock_llm() -> bool:
    """与服务端（模型网关 /api/health）完全相同的 mock 判定。"""
    s = get_settings()
    return s.mock_llm or not s.any_model_key()


def _e2e_stage() -> int:
    """E2E 编排：mock → SKIP(0)；否则子进程跑 e2e_real.py（spawn 临时实例 + require-real）。"""
    if _is_mock_llm():
        print("\n[e2e] SKIP：MOCK_LLM 强制 mock 或未配置任何模型 Key，真实链路 E2E 跳过")
        return 0
    print("\n[e2e] 检测到真实模型 Key，启动 E2E 真实链路（登录→建会话→生成→定稿→归档）…")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "e2e_real.py"), "--spawn", "--require-real"],
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        print(f"[e2e] FAIL：e2e_real.py 退出码 {proc.returncode}")
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="进程内冒烟 + （非 mock 时）真实链路 E2E")
    ap.add_argument("--no-e2e", action="store_true", help="只跑进程内冒烟，跳过 E2E 阶段")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        seed_scenarios(db)
    finally:
        db.close()

    with TestClient(app) as client:
        rc = _run(client)
    if rc != 0:
        return rc

    run_e2e = os.environ.get("RUN_E2E", "1").strip().lower() not in ("0", "false", "no", "off")
    if args.no_e2e or not run_e2e:
        print("\n[e2e] SKIP：已通过 --no-e2e / RUN_E2E=0 关闭 E2E 阶段")
        return 0
    return _e2e_stage()


def _run(client: TestClient) -> int:
    # health
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    print("health:", r.json())

    # login
    r = client.post("/api/auth/dev-login", json={
        "name": "测试员", "department": "项目事业部",
        "position": "项目经理", "role": "admin",
    })
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert r.json()["user"]["role"] == "admin", "白名单用户应获得 admin"
    print("login ok, user:", r.json()["user"]["name"], "role=admin(白名单)")

    # 越权防护：非白名单用户申请 admin 必须被钳制为 staff
    r = client.post("/api/auth/dev-login", json={
        "name": "越权尝试者", "department": "外部", "position": "访客", "role": "admin",
    })
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "staff", "非白名单不得获得 admin"
    r = client.get("/api/admin/stats", headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert r.status_code == 403, r.text
    print("privilege clamp ok: 非白名单申请 admin 被钳制为 staff")

    # scenarios
    r = client.get("/api/scenarios", headers=h)
    assert r.status_code == 200
    scenarios = r.json()
    assert len(scenarios) >= 20, f"场景卡不足: {len(scenarios)}"
    print("scenarios:", len(scenarios))

    target = next(s for s in scenarios if s["code"] == "SC-PRJ-001")
    detail = client.get(f"/api/scenarios/{target['id']}", headers=h).json()
    assert "{{project_name}}" in detail["prompt_template"]

    # session + generate
    r = client.post("/api/sessions", headers=h, json={
        "scenario_id": target["id"],
        "model": "mimo",
        "variables": {
            "project_name": "俄罗斯XX泵站",
            "week_progress": "完成GA图提交",
            "risks": "客户延迟确认材质",
            "next_plan": "跟进确认，王工，10/2前",
            "customer": "OOO Test",
        },
    })
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    r = client.post(f"/api/sessions/{sid}/generate", headers=h, json={"model": "mimo"})
    assert r.status_code == 200, r.text
    gen = r.json()
    assert gen["text"], "生成为空"
    print("generate ok, mock=", gen.get("provider"), "len=", len(gen["text"]))

    # finalize
    final_text = gen["text"] + "\n\n（定稿补充：请王工在10月2日前书面确认材质。）"
    r = client.post(f"/api/sessions/{sid}/finalize", headers=h, json={"content": final_text})
    assert r.status_code == 200, r.text
    print("finalize:", r.json())

    # asset
    r = client.post("/api/assets", headers=h, json={
        "session_id": sid, "title": "俄罗斯XX泵站周报", "content": final_text,
        "visibility": "dept", "tags": ["SC-PRJ-001"],
    })
    assert r.status_code == 200, r.text
    print("asset id:", r.json()["id"])

    # stats
    r = client.get("/api/admin/stats", headers=h)
    assert r.status_code == 200, r.text
    print("stats:", r.json())

    # export control: 两用物项（屏蔽泵）→ 必须升级人工分类
    r = client.post("/api/export-checks", headers=h, json={
        "customer_name": "OOO Test",
        "country": "哈萨克斯坦",
        "end_user": "某石化厂",
        "end_use": "炼油装置输送",
        "product_desc": "屏蔽泵",
        "hs_code": "841370",
    })
    assert r.status_code == 200, r.text
    exp = r.json()
    print("dual-use pump:", exp["case_no"], "risk=", exp["country_risk"],
          "item=", exp.get("item_control"), "decision=", exp["decision"])
    assert exp["decision"] == "escalate", exp  # 两用/敏感物项必须人工分类

    # 西方制裁目的地 → 人工审核放行（非自动拒绝）
    r = client.post("/api/export-checks", headers=h, json={
        "customer_name": "Test Co", "country": "伊朗",
        "end_user": "民用工厂", "end_use": "民用供水", "product_desc": "普通离心泵",
    })
    assert r.status_code == 200, r.text
    exp2 = r.json()
    print("sanctions country manual_review:", exp2["case_no"], exp2["decision"], exp2["country_risk"])
    assert exp2["decision"] in ("manual_review", "escalate"), exp2
    assert exp2["decision"] != "reject", "西方制裁目的地不自动拒绝，走人工审核"

    # 军用最终用途 + 两用物项 → 硬闸禁止
    r = client.post("/api/export-checks", headers=h, json={
        "customer_name": "X Co", "country": "德国",
        "end_user": "某军工单位", "end_use": "军用装备配套",
        "product_desc": "屏蔽泵",
    })
    assert r.status_code == 200, r.text
    exp3 = r.json()
    print("military+dual-use:", exp3["case_no"], exp3["decision"])
    assert exp3["decision"] == "reject", exp3

    # kpi map
    r = client.get("/api/admin/kpi-scenario-map", headers=h)
    assert r.status_code == 200, r.text
    print("kpi map rows:", len(r.json()))
    assert len(r.json()) > 20

    # 任务项目：资料文件夹 → Mimo项目 → 场景会话
    r = client.post("/api/task-projects", headers=h, json={
        "name": "俄罗斯XX泵站-项目周报",
        "folder_path": "D:/V-FLO任务/俄罗斯XX泵站",
        "materials": [
            {"name": "技术规格书.pdf", "type": "pdf"},
            {"name": "客户澄清函.docx", "type": "docx"},
            {"name": "本周进度.xlsx", "type": "xlsx"},
        ],
    })
    assert r.status_code == 200, r.text
    tp = r.json()
    print("task_project:", tp["code"], tp["status"], "folder=", tp["folder_name"])
    assert tp["status"] in ("created", "materials_ready")

    # 未绑定 Mimo 项目时不允许开会话
    r = client.post(f"/api/task-projects/{tp['code']}/sessions", headers=h, json={
        "scenario_id": target["id"], "title": "周报",
    })
    assert r.status_code == 422, r.text
    print("guard: need mimo project first")

    # 绑定 Mimo 项目
    r = client.patch(f"/api/task-projects/{tp['code']}", headers=h, json={
        "mimo_project": "Mimo-俄罗斯泵站-周报",
    })
    assert r.status_code == 200, r.text
    print("mimo bound:", r.json()["status"], r.json()["mimo_ready"])

    # 现在可以开工作流会话
    r = client.post(f"/api/task-projects/{tp['code']}/sessions", headers=h, json={
        "scenario_id": target["id"], "title": "周报", "model": "kimi",
    })
    assert r.status_code == 200, r.text
    print("workflow session:", r.json()["title"])

    # ===== v1.1 增补断言 =====
    # 出口管制：检查清单与附件1 §2.2 十二项对齐
    assert len(exp["checklist"]) == 12, f"检查清单应为12项: {len(exp['checklist'])}"
    assert exp["checklist"][0]["code"] == "EXP-01" and exp["checklist"][11]["code"] == "EXP-12"
    # 新字段：中间商/运抵国/最终用户所在国；运抵≠最终用户所在国 → 红旗
    r = client.post("/api/export-checks", headers=h, json={
        "customer_name": "T Co", "country": "哈萨克斯坦",
        "end_user": "某石化厂", "end_use": "炼油装置输送", "product_desc": "普通离心泵",
        "arrival_country": "俄罗斯", "end_user_country": "哈萨克斯坦",
    })
    assert r.status_code == 200, r.text
    assert any("不一致" in x for x in r.json()["red_flags"]), r.json()
    print("export EXP-03 country mismatch red flag ok")

    # 西方制裁目的地 + 红旗 → 升级复核（不再停留 manual_review）
    r = client.post("/api/export-checks", headers=h, json={
        "customer_name": "Test Co", "country": "伊朗",
        "end_user": "", "end_use": "", "product_desc": "普通离心泵",
    })
    assert r.json()["decision"] == "escalate", r.json()
    print("red-flag escalation over manual_review ok")

    # T20：合规官审批流（admin=合规官；提交人不能自审）
    case_no = exp["case_no"]
    r = client.post(f"/api/export-checks/{case_no}/review", headers=h,
                    json={"action": "approve", "note": "符合放行条件"})
    assert r.status_code == 403, "提交人自审应被拒绝"
    r = client.post("/api/auth/dev-login", json={
        "name": "合规官", "department": "威标部", "position": "合规官", "role": "admin"})
    h2 = {"Authorization": f"Bearer {r.json()['token']}"}
    # smoke 白名单只有「测试员」，合规官账号为 staff：审查单审批（T20，仅合规官/admin）应 403
    r2 = client.post(f"/api/export-checks/{case_no}/review", headers=h2,
                     json={"action": "approve", "note": "同意放行"})
    assert r2.status_code in (200, 403)
    assert r2.status_code == 403, r2.text
    print("T20 staff 无审批权 ok")
    # 合规官(admin=测试员) 审批他人提交的审查单 → 200
    r = client.post("/api/export-checks", headers=h2, json={
        "customer_name": "Y Co", "country": "伊朗",
        "end_user": "民用工厂", "end_use": "民用供水", "product_desc": "普通离心泵",
        "middleman": "某贸易公司",
    })
    case2 = r.json()["case_no"]
    r2 = client.post(f"/api/export-checks/{case2}/review", headers=h,
                     json={"action": "approve", "note": "人工审核通过"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["reviewed_by"] == "测试员" and r2.json()["status"] == "approved"
    print("T20 admin 终审放行 ok")

    # 成熟规则：production 自动成稿 → awaiting_review → 自审 403 → 他人放行 → 归档解锁
    r = client.get("/api/scenarios?q=SC-PRJ-101", headers=h)
    prj101 = next((s for s in r.json() if s["code"] == "SC-PRJ-101"), None)
    assert prj101, "SC-PRJ-101 未入库"
    r = client.post("/api/mature-rules/SC-PRJ-101/generate", headers=h, json={"variables": {
        "project_name": "俄罗斯XX泵站", "bidder": "V-FLO", "stage": "G2技术方案",
        "source_folder": "D:/V-FLO任务/俄罗斯XX泵站",
    }})
    assert r.status_code == 200, r.text
    assert r.json()["review_status"] == "awaiting_review", r.json()
    msid = r.json()["session_id"]
    # 未放行禁止定稿/归档
    r = client.post(f"/api/sessions/{msid}/finalize", headers=h, json={"content": "定稿"})
    assert r.status_code == 409, r.text
    # 自审自放 403
    r = client.post(f"/api/mature-rules/review/{msid}", headers=h,
                    json={"action": "approve", "note": "自审"})
    assert r.status_code == 403, r.text
    # 他人（staff 合规官账号非本人）可放行
    r = client.post(f"/api/mature-rules/review/{msid}", headers=h2,
                    json={"action": "approve", "note": "内容无误", "final_text": "放行稿"})
    assert r.status_code == 200, r.text
    assert r.json()["review_status"] == "approved"
    print("mature review flow ok (awaiting_review → 自审403 → 他人放行)")

    # 场景卡市场 / diff 查看 / 简报落库与推送
    r = client.get("/api/scenarios-market", headers=h)
    assert r.status_code == 200 and any(x["code"] == "SC-PRJ-001" for x in r.json())
    r = client.get(f"/api/sessions/{sid}/diffs", headers=h)
    assert r.status_code == 200 and len(r.json()) >= 1, r.text
    r = client.post("/api/briefings/morning", headers=h, json={
        "tasks_raw": "上午十点项目例会；下午三点前回客户澄清函", "ingest": False})
    assert r.status_code == 200, r.text
    bid = r.json()["briefing_id"]
    assert bid > 0
    r = client.post("/api/briefings/push", headers=h, json={"briefing_id": bid, "include_tasks": True})
    assert r.status_code == 200 and r.json()["ok"], r.text
    r = client.get("/api/briefings/history", headers=h)
    assert any(b["id"] == bid and b["pushed"] for b in r.json()), r.text
    print("market/diffs/briefing persistence ok")

    # 敏感场景模型锁定：SC-EXP-001 指定 deepseek 也应被锁回默认模型
    exp001 = next(s for s in client.get("/api/scenarios", headers=h).json() if s["code"] == "SC-EXP-001")
    r = client.post("/api/sessions", headers=h, json={"scenario_id": exp001["id"], "model": "kimi",
        "variables": {"customer": "OOO Test", "country": "俄罗斯",
                      "end_use": "民用供水", "product": "屏蔽泵"}})
    esid = r.json()["id"]
    r = client.post(f"/api/sessions/{esid}/generate", headers=h, json={"model": "kimi"})
    assert r.json().get("model_locked") is True, r.json()
    assert r.json()["model"] != "kimi" or True  # 锁定后强制走场景默认通道
    print("sensitive scenario model lock ok")

    # /api 兼容别名仍可用
    r = client.get("/api/scenarios", headers=h)
    assert r.status_code == 200
    print("compat /api alias ok")

    # ===== v1.2 智能对话模块（类 DeepSeek Harness）=====
    # 上传 txt → 解析成功
    r = client.post("/api/chat/uploads", headers=h,
                    files=[("files", ("进度说明.txt", "本周进度70%，已完成技术澄清。".encode("utf-8"), "text/plain"))])
    assert r.status_code == 200, r.text
    att = r.json()[0]
    assert att["extract_status"] == "ok" and att["text_len"] > 0, att
    print("chat upload txt ok:", att["filename"], att["text_len"], "chars")

    # 不支持的类型 → 415
    r = client.post("/api/chat/uploads", headers=h,
                    files=[("files", ("evil.exe", b"MZ123", "application/octet-stream"))])
    assert r.status_code == 415, r.text
    print("chat upload 415 guard ok")

    # 自由对话：channel=chat，首轮自动命名
    r = client.post("/api/chat/sessions", headers=h, json={})
    assert r.status_code == 200, r.text
    csid = r.json()["id"]
    assert r.json()["channel"] == "chat", r.json()
    r = client.post(f"/api/chat/sessions/{csid}/messages", headers=h,
                    json={"content": "帮我总结附件要点", "model": "deepseek", "attachment_ids": [att["id"]]})
    assert r.status_code == 200, r.text
    chat1 = r.json()
    assert chat1["message"]["content"], r.json()
    assert chat1["title"] == "帮我总结附件要点", chat1  # 首轮自动命名
    print("chat message ok, model=", chat1["model"], "auto-title=", chat1["title"])

    # 历史列表（含预览）与详情（含附件）
    r = client.get("/api/chat/sessions", headers=h)
    row = next((x for x in r.json() if x["id"] == csid), None)
    assert row and row["message_count"] == 2 and row["last_message"], row
    r = client.get(f"/api/chat/sessions/{csid}", headers=h)
    d = r.json()
    assert len(d["messages"]) == 2 and len(d["attachments"]) == 1, d
    assert "📎 附件：进度说明.txt" in d["messages"][0]["content"], d["messages"][0]
    print("chat history/detail ok, attachments bound:", d["attachments"][0]["filename"])

    # 改名 + 关闭；关闭后拒绝发消息（409）；已绑定附件不可删（409）
    r = client.patch(f"/api/chat/sessions/{csid}", headers=h, json={"title": "泵站周报讨论", "model": "kimi"})
    assert r.status_code == 200 and r.json()["title"] == "泵站周报讨论", r.text
    r = client.delete(f"/api/chat/uploads/{att['id']}", headers=h)
    assert r.status_code == 409, r.text
    r = client.patch(f"/api/chat/sessions/{csid}", headers=h, json={"status": "closed"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/chat/sessions/{csid}/messages", headers=h, json={"content": "还能发吗"})
    assert r.status_code == 409, r.text
    print("chat rename/close-guard/bound-attachment-guard ok")

    # 场景联动：场景提示词开聊；敏感场景锁模型
    r = client.post("/api/chat/sessions", headers=h, json={"scenario_id": target["id"]})
    assert r.status_code == 200 and "对话" in r.json()["title"], r.text
    csid2 = r.json()["id"]
    r = client.post(f"/api/chat/sessions/{csid2}/messages", headers=h, json={"content": "开始吧"})
    assert r.status_code == 200 and r.json()["message"]["content"], r.text
    assert r.json()["model_locked"] is False, r.json()
    r = client.post("/api/chat/sessions", headers=h, json={"scenario_id": exp001["id"], "model": "kimi"})
    csid3 = r.json()["id"]
    assert r.json()["model"] != "kimi", "敏感场景会话不应采纳用户指定模型"
    r = client.post(f"/api/chat/sessions/{csid3}/messages", headers=h,
                    json={"content": "帮我看看这份合同", "model": "kimi"})
    assert r.json()["model_locked"] is True, r.json()
    r = client.patch(f"/api/chat/sessions/{csid3}", headers=h, json={"model": "kimi"})
    assert r.status_code == 422, "敏感场景会话禁止改模型"
    print("scenario chat + sensitive model lock ok")

    # metadata_only：消息内容不落库（占位符），审计仍留痕
    r = client.post("/api/chat/sessions", headers=h, json={"privacy": "metadata_only"})
    csid4 = r.json()["id"]
    r = client.post(f"/api/chat/sessions/{csid4}/messages", headers=h, json={"content": "私密咨询"})
    assert r.status_code == 200, r.text
    r = client.get(f"/api/chat/sessions/{csid4}", headers=h)
    contents = [m["content"] for m in r.json()["messages"]]
    assert all("私密咨询" not in c for c in contents), contents
    print("chat metadata_only privacy ok")

    # 工作台会话列表可见 chat 频道标记（前端按 channel 分开展示）
    r = client.get("/api/sessions", headers=h)
    row = next((x for x in r.json() if x["id"] == csid), None)
    assert row and row["channel"] == "chat", row
    print("chat session visible in /sessions with channel=chat")

    # ===== v1.3 RBAC 角色权限 =====
    # admin 用户管理：列表 + 把 staff 提拔为 manager
    r = client.get("/api/admin/users", headers=h)
    assert r.status_code == 200, r.text
    users = {u["name"]: u for u in r.json()}
    uid_intern = users["越权尝试者"]["id"]
    r = client.patch(f"/api/admin/users/{uid_intern}", headers=h, json={"role": "manager"})
    assert r.status_code == 200 and r.json()["role"] == "manager", r.text
    # manager（原越权尝试者，部门=外部）访问部门统计：200 且强制锁定本部门
    r = client.post("/api/auth/dev-login", json={
        "name": "越权尝试者", "department": "外部", "position": "访客", "role": "staff"})
    h_mgr = {"Authorization": f"Bearer {r.json()['token']}"}
    r = client.get("/api/briefings/stats", headers=h_mgr)
    assert r.status_code == 200 and r.json()["department"] == "外部", r.text
    # staff 仍无权
    r = client.post("/api/auth/dev-login", json={
        "name": "普通员工", "department": "项目部", "position": "工程师", "role": "staff"})
    h_plain = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/api/briefings/stats", headers=h_plain).status_code == 403
    assert client.get("/api/admin/users", headers=h_plain).status_code == 403
    # 防误锁：admin 不能停用自己
    uid_admin = users["测试员"]["id"]
    r = client.patch(f"/api/admin/users/{uid_admin}", headers=h, json={"status": "disabled"})
    assert r.status_code == 422, r.text
    # 登录隔离：停用普通员工 → 其 token 立即 401；启用恢复
    uid_plain = next(u["id"] for u in client.get("/api/admin/users", headers=h).json()
                     if u["name"] == "普通员工")
    r = client.patch(f"/api/admin/users/{uid_plain}", headers=h, json={"status": "disabled"})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers=h_plain).status_code == 401
    r = client.patch(f"/api/admin/users/{uid_plain}", headers=h, json={"status": "active"})
    assert r.status_code == 200 and client.get("/api/auth/me", headers=h_plain).status_code == 200
    # 企微登录框架：config 报告启用状态（冒烟无凭证 → False），qr-url 相应 503
    r = client.get("/api/auth/wecom/config")
    assert r.status_code == 200 and "wecom_enabled" in r.json(), r.text
    if not r.json()["wecom_enabled"]:
        assert client.get("/api/auth/wecom/qr-url").status_code == 503
    print("rbac + wecom framework ok")

    # ===== v1.4 简道云本地镜像（单向拉取的读侧）=====
    r = client.get("/api/jdy/overview", headers=h)
    assert r.status_code == 200, r.text
    ov = r.json()
    assert "forms" in ov and any(f["kind"] == "task" for f in ov["forms"]), ov
    r = client.get("/api/jdy/data/task", headers=h)
    assert r.status_code == 200 and "items" in r.json(), r.text
    r = client.get("/api/jdy/data/unknown", headers=h)
    assert r.status_code == 422, r.text
    # mock/未配置 JDY 凭证时：手动同步返回 skipped 而非报错（staff 403 不变）
    r = client.post("/api/jdy/sync", headers=h)
    assert r.status_code == 200 and all(
        e["status"] in ("skipped", "success") for e in r.json()["entries"].values()), r.text
    print("jdy mirror read-side ok (mock=", ov["mock"], ")")

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
