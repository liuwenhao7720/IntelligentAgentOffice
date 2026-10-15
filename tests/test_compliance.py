# -*- coding: utf-8 -*-
"""合规审查前移 + 规则资料配置专项测试。

直接运行：python tests/test_compliance.py
- 进程内 TestClient + 独立临时 SQLite，无真实网络（MOCK_LLM）
- 覆盖：
  1) 规则资产：种子幂等 / 分组读取 / 权限 / 启停用即时生效（配置化）
  2) 资料资产：选型软件等资源可调用
  3) 审查前移：项目初步分析阶段初筛 → 绑定项目 → 终审 → 状态流转；
     已有结论不重复审查（409），force 重新审查换绑
  4) 工作台只调用审查结果：项目会话出口场景未放行 409 阻断、放行后生成成功、
     生成过程不产生新审查单（不重复审查）、非出口场景不阻断
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="vflo_comp_test_"))
os.environ["MOCK_LLM"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["DEV_ADMIN_USERS"] = "管理员甲"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.database import ExportCheck, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: object = "") -> None:
    if cond:
        print(f"  ok  {name}")
    else:
        FAILED.append(name)
        print(f" FAIL {name} :: {detail}")


def login(client: TestClient, name: str, dept: str = "商务部", role: str = "staff") -> dict:
    r = client.post("/api/v1/auth/dev-login",
                    json={"name": name, "department": dept, "position": "工程师", "role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def check_count() -> int:
    db = SessionLocal()
    try:
        return db.execute(select(func.count()).select_from(ExportCheck)).scalar() or 0
    finally:
        db.close()


def main() -> int:
    with TestClient(app) as client:
        h_staff = login(client, "销售乙")
        h_admin = login(client, "管理员甲", role="admin")
        h_comp = login(client, "合规官丙", dept="威标部")
        users = {u["name"]: u for u in client.get("/api/v1/admin/users", headers=h_admin).json()}
        client.patch(f"/api/v1/admin/users/{users['合规官丙']['id']}", headers=h_admin,
                     json={"role": "compliance"})

        print("[rules] 规则资产：种子/读取/权限")
        r = client.get("/api/v1/compliance/rules", headers=h_staff)
        check("规则读取 200（全员可看）", r.status_code == 200, r.text)
        cats = {g["category"]: g for g in r.json()["categories"]}
        check("七类规则齐全（country/item/redline/redflag/checklist/note/resource）",
              set(cats) >= {"country_list", "item_hints", "end_use_redline", "red_flag",
                            "checklist", "decision_note", "resource"}, list(cats))
        check("十二项检查清单", len(cats["checklist"]["items"]) == 12, cats["checklist"]["items"][:2])
        check("staff 不可编辑", r.json()["can_edit"] is False, r.json())
        r = client.get("/api/v1/compliance/rules")
        check("未登录 401", r.status_code == 401, r.status_code)

        r = client.get("/api/v1/compliance/resources", headers=h_staff)
        check("资料资产 200", r.status_code == 200, r.text)
        res_names = [x["name"] for x in r.json()]
        check("选型软件已配置", any("选型" in n and "软件" in n for n in res_names), res_names)

        print("[rules] 配置化：停用 industrial 提示词 → 屏蔽泵不再命中两用")
        ind = next(x for x in cats["item_hints"]["items"] if x["code"] == "industrial")
        r = client.patch(f"/api/v1/compliance/rules/{ind['id']}", headers=h_staff,
                         json={"enabled": False})
        check("staff 停用规则 403", r.status_code == 403, r.status_code)
        r = client.patch(f"/api/v1/compliance/rules/{ind['id']}", headers=h_comp,
                         json={"enabled": False})
        check("合规官停用规则 200", r.status_code == 200, r.text)
        # 用独立审查单验证判定变化（屏蔽泵不再命中工业两用 → 非 dual_use）
        r = client.post("/api/v1/export-checks", headers=h_staff, json={
            "customer_name": "配置化验证Co", "country": "美国", "end_user": "配置化验证Co",
            "end_use": "民用市政供水", "product_desc": "屏蔽泵2台"})
        check("停用后判定 civil（配置化生效）",
              r.status_code == 200 and r.json()["item_control"] == "civil?",
              (r.status_code, r.json().get("item_control")))
        client.patch(f"/api/v1/compliance/rules/{ind['id']}", headers=h_comp, json={"enabled": True})
        r = client.post("/api/v1/export-checks", headers=h_staff, json={
            "customer_name": "配置化验证Co", "country": "美国", "end_user": "配置化验证Co",
            "end_use": "民用市政供水", "product_desc": "屏蔽泵2台"})
        check("恢复启用后命中两用", r.json()["item_control"] == "dual_use", r.json()["item_control"])

        print("[前移] 项目初步分析阶段完成审查")
        r = client.post("/api/v1/task-projects", headers=h_staff, json={
            "name": "俄罗斯泵站供货", "customer_name": "ABC Trading", "country": "俄罗斯"})
        check("建项目（带初步分析要素）200", r.status_code == 200, r.text)
        pcode = r.json()["code"]
        check("项目要素落库", r.json()["customer_name"] == "ABC Trading" and r.json()["country"] == "俄罗斯", r.json())

        r = client.get(f"/api/v1/task-projects/{pcode}/compliance", headers=h_staff)
        check("未审查状态 none", r.json()["state"] == "none", r.json())

        # 缺关键要素 422（新建一个无要素项目）
        p2 = client.post("/api/v1/task-projects", headers=h_staff, json={"name": "空项目"}).json()["code"]
        r = client.post(f"/api/v1/task-projects/{p2}/screening", headers=h_staff, json={})
        check("缺客户/国别 422", r.status_code == 422, r.status_code)

        n0 = check_count()
        r = client.post(f"/api/v1/task-projects/{pcode}/screening", headers=h_staff, json={
            "end_user": "俄油某厂", "end_use": "石化厂民用注水", "product_desc": "普通离心泵2台",
        })
        check("项目初筛 200", r.status_code == 200, r.text)
        case_no = r.json()["case_no"]
        check("审查单绑定项目", r.json()["task_project_code"] == pcode, r.json())
        check("初筛结论（民用+俄罗斯→人工审核/升级）",
              r.json()["decision"] in ("manual_review", "escalate"), r.json()["decision"])
        check("审查单 +1", check_count() == n0 + 1, check_count())

        r = client.get(f"/api/v1/task-projects/{pcode}/compliance", headers=h_staff)
        check("状态=待终审/升级", r.json()["state"] in ("reviewing", "escalated"), r.json())
        check("合规摘要含单号", r.json()["case_no"] == case_no, r.json())

        # 项目列表装配合规摘要
        r = client.get("/api/v1/task-projects", headers=h_staff)
        row = next(x for x in r.json() if x["code"] == pcode)
        check("项目列表带合规摘要", row["compliance"] and row["compliance"]["case_no"] == case_no, row.get("compliance"))

        # 在途单重复发起 → 409（不重复审查）
        r = client.post(f"/api/v1/task-projects/{pcode}/screening", headers=h_staff,
                        json={"end_use": "民用注水", "product_desc": "普通离心泵2台"})
        check("在途重复审查 409", r.status_code == 409, r.status_code)

        print("[前移] 工作台只调用审查结果，不重复审查")
        # 出口管制场景卡（种子 SC-EXP-001，security_level=export_control）
        scenarios = client.get("/api/v1/scenarios", headers=h_staff).json()
        sc_exp = next(s for s in scenarios if s["code"] == "SC-EXP-001")
        sc_normal = next(s for s in scenarios if s["security_level"] == "normal")
        norm_vars = {v["key"]: "测试值" for v in (sc_normal.get("variables") or [])
                     if v.get("required", True)}

        # 绑定 Mimo 后开项目会话
        client.patch(f"/api/v1/task-projects/{pcode}", headers=h_staff, json={"mimo_project": "俄泵项目"})
        r = client.post(f"/api/v1/task-projects/{pcode}/sessions", headers=h_staff,
                        json={"scenario_id": sc_exp["id"], "title": "项目内出口审查场景"})
        check("项目会话 200", r.status_code == 200, r.text)
        sid_exp = r.json()["id"]
        check("会话绑定项目", r.json()["task_project_code"] == pcode, r.json())

        n1 = check_count()
        r = client.post(f"/api/v1/sessions/{sid_exp}/generate", headers=h_staff, json={
            "variables": {"customer": "ABC Trading", "country": "俄罗斯",
                          "end_user": "俄油某厂", "end_use": "民用注水", "product": "离心泵"}})
        check("未放行时出口场景 409 阻断", r.status_code == 409, r.status_code)
        check("409 带 compliance_required", r.json().get("error_code") == "compliance_required", r.json())
        check("阻断不产生新审查单（不重复审查）", check_count() == n1, check_count())

        # 合规官终审放行（提交人是销售乙，合规官可审）
        r = client.post(f"/api/v1/export-checks/{case_no}/review", headers=h_comp,
                        json={"action": "approve", "note": "民用+非受控物项，放行"})
        check("合规官终审放行 200", r.status_code == 200, r.text)
        check("终审决策 pass", r.json()["decision"] == "pass", r.json()["decision"])
        check("终审不能自审 403",
              client.post(f"/api/v1/export-checks/{case_no}/review", headers=h_staff,
                          json={"action": "approve"}).status_code == 403, "提交人自审应被拒")

        r = client.get(f"/api/v1/task-projects/{pcode}/compliance", headers=h_staff)
        check("终审后状态 approved", r.json()["state"] == "approved", r.json())

        n2 = check_count()
        r = client.post(f"/api/v1/sessions/{sid_exp}/generate", headers=h_staff, json={
            "variables": {"customer": "ABC Trading", "country": "俄罗斯",
                          "end_user": "俄油某厂", "end_use": "民用注水", "product": "离心泵"}})
        check("放行后生成 200", r.status_code == 200, r.text[:200])
        comp = r.json().get("compliance") or {}
        check("响应带回审查结论", comp.get("state") == "approved" and comp.get("case_no") == case_no, comp)
        check("生成不新增审查单（只读结果）", check_count() == n2, check_count())

        # 已放行项目重复审查 → 409；force=true → 换绑新单
        r = client.post(f"/api/v1/task-projects/{pcode}/screening", headers=h_staff,
                        json={"end_use": "民用注水", "product_desc": "离心泵"})
        check("已放行重复审查 409", r.status_code == 409, r.status_code)
        r = client.post(f"/api/v1/task-projects/{pcode}/screening", headers=h_staff,
                        json={"end_use": "民用注水", "product_desc": "离心泵", "force": True})
        check("force 重新审查 200", r.status_code == 200, r.text[:150])
        new_no = r.json()["case_no"]
        check("换绑新审查单", new_no != case_no and r.json()["task_project_code"] == pcode, new_no)
        r = client.get(f"/api/v1/task-projects/{pcode}/compliance", headers=h_staff)
        check("换绑后状态回到在途", r.json()["case_no"] == new_no
              and r.json()["state"] in ("reviewing", "escalated"), r.json())

        # 非出口场景：项目未放行也不阻断（仅带信息）
        r = client.post(f"/api/v1/task-projects/{pcode}/sessions", headers=h_staff,
                        json={"scenario_id": sc_normal["id"], "title": "项目内普通场景"})
        sid_norm = r.json()["id"]
        r = client.post(f"/api/v1/sessions/{sid_norm}/generate", headers=h_staff,
                        json={"variables": norm_vars})
        check("非出口场景不阻断", r.status_code == 200, r.text[:150])
        check("响应仍带合规信息", (r.json().get("compliance") or {}).get("case_no") == new_no, r.json().get("compliance"))

        print("[出口管制页签] 独立审查绑定项目 + 按项目过滤 + 合规官可见")
        r = client.post("/api/v1/export-checks", headers=h_staff, json={
            "customer_name": "XYZ Ltd", "country": "美国", "end_user": "XYZ Ltd",
            "end_use": "民用", "product_desc": "普通水泵", "task_project_code": pcode})
        check("独立审查绑定项目 200", r.status_code == 200 and r.json()["task_project_code"] == pcode, r.json())
        r = client.get(f"/api/v1/export-checks?project={pcode}", headers=h_staff)
        check("按项目过滤", r.status_code == 200 and
              all(x["task_project_code"] == pcode for x in r.json()) and len(r.json()) >= 2, len(r.json()))
        r = client.get("/api/v1/export-checks", headers=h_comp)
        check("合规官可见全部审查单（终审职责）", r.status_code == 200 and
              any(x["case_no"] == new_no for x in r.json()), len(r.json()))
        r = client.post("/api/v1/export-checks", headers=h_staff, json={
            "customer_name": "X", "country": "美国", "task_project_code": "TP-NOT-EXIST"})
        check("绑定不存在项目 404", r.status_code == 404, r.status_code)

        print("[无项目会话] 不受闸口影响（独立使用出口场景卡）")
        r = client.post("/api/v1/sessions", headers=h_staff,
                        json={"scenario_id": sc_exp["id"], "title": "独立初筛场景",
                              "variables": {"customer": "A", "country": "美国",
                                            "end_user": "A", "end_use": "民用", "product": "水泵"}})
        sid_free = r.json()["id"]
        r = client.post(f"/api/v1/sessions/{sid_free}/generate", headers=h_staff,
                        json={"variables": {"customer": "A", "country": "美国",
                                            "end_user": "A", "end_use": "民用", "product": "水泵"}})
        check("无项目出口场景可生成（独立初筛工具）", r.status_code == 200, r.status_code)
        check("无项目时 compliance 为空", r.json().get("compliance") is None, r.json().get("compliance"))

    if FAILED:
        print(f"\nTEST_COMPLIANCE FAILED: {len(FAILED)} 项 -> {FAILED}")
        return 1
    print("\nTEST_COMPLIANCE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
