# -*- coding: utf-8 -*-
"""冒烟测试：登录 → 选场景 → 生成 → 定稿 → 知产 → 统计。
直接对内存/SQLite 跑，不依赖已启动服务。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed.scenarios import seed_scenarios  # noqa: E402


def main() -> int:
    init_db()
    db = SessionLocal()
    try:
        seed_scenarios(db)
    finally:
        db.close()

    with TestClient(app) as client:
        return _run(client)


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
    print("login ok, user:", r.json()["user"]["name"])

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

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
