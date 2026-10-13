# -*- coding: utf-8 -*-
"""今日工作安排（手册 1.5）专项验证：迁移 → 采集 → 入池 → 时间轴 → 完成 → 溢出 → 改期 → 早宣入池 → 领导模式 → 审计。
运行：python3 tests/test_today.py
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path("/tmp/vflo_today_test")
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)
DB = TMP / "t.db"

# 0) 构造「旧结构」遗留库：task_items 无三态列，验证 migrate_db 补列
conn = sqlite3.connect(DB)
conn.execute("CREATE TABLE task_items (id INTEGER PRIMARY KEY, title VARCHAR(256))")
conn.commit(); conn.close()

os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["MOCK_LLM"] = "1"
# 测试确定性：强制简道云 MOCK（容器环境可能带真实 JDY key）
os.environ["JDY_APP_ID"] = ""
os.environ["JDY_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db, migrate_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
migrate_db()
cols = {r[1] for r in sqlite3.connect(DB).execute("PRAGMA table_info(task_items)")}
assert {"is_meeting", "is_other_request", "is_today_fixed"} <= cols, f"迁移缺列: {cols}"
print("0. 遗留库迁移补列 OK")

# 迁移验证通过后重建为完整新结构，供后续 API 测试使用
conn = sqlite3.connect(DB)
conn.execute("DROP TABLE task_items")
conn.commit(); conn.close()
init_db()

passed = []
with TestClient(app) as c:
    r = c.post("/api/auth/dev-login", json={"name": "核查员", "department": "项目部", "position": "项目经理"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}

    # 1) 口语采集：会议识别 + 固定时间 + 明日截止
    r = c.post("/api/tasks/capture", headers=h, json={
        "text": "上午10点项目例会；下午3点前回客户澄清函；明天交周报初稿",
        "source": "chat", "use_llm": True,
    })
    cands = r.json()["candidates"]
    meeting = next((x for x in cands if "例会" in x["title"]), None)
    assert meeting and meeting["is_meeting"] and meeting["ai_fixed_start"] == "10:00", cands
    assert any(x.get("due_time") for x in cands), cands
    passed.append("1. 口语拆解：会议🔒10:00 / 明日截止 识别 OK")

    # 2) 确认入池（去重）
    r = c.post("/api/tasks/ingest", headers=h, json={"items": cands})
    assert r.json()["created"] == 3, r.json()
    r2 = c.post("/api/tasks/ingest", headers=h, json={"items": cands})
    assert r2.json()["skipped_dup"] == 3, r2.json()
    passed.append("2. 入池 3 条 + 重复入池全部去重 OK")

    # 3) 今日时间轴：B0 固定会议在最前
    d = c.get("/api/tasks/today", headers=h).json()
    assert d["timeline"][0]["bucket"] == "B0" and "例会" in d["timeline"][0]["title"], d["timeline"][0]
    assert d["summary"]["fixed"] >= 1 and "今日固定/他人要求" in d["summary"]["by_type"]
    passed.append("3. B0 固定会议置顶 + 三分类计数 OK")

    # 4) 完成会议 → 移出今日
    mid = d["timeline"][0]["task"]["id"]
    r = c.post(f"/api/tasks/{mid}/status", headers=h, json={"status": "已完成"})
    assert r.json()["status"] == "已完成"
    d2 = c.get("/api/tasks/today", headers=h).json()
    assert all("例会" not in x["title"] for x in d2["timeline"])
    r = c.post(f"/api/tasks/{mid}/status", headers=h, json={"status": "删掉"})
    assert r.status_code == 422
    passed.append("4. 完成移出今日 + 非法状态 422 OK")

    # 5) 溢出：8 个 3h 大件必然溢出
    items = [{"title": f"大件任务{i}", "estimated_hours": 3, "ai_urgency": 3, "ai_importance": 2} for i in range(8)]
    c.post("/api/tasks/ingest", headers=h, json={"items": items})
    d3 = c.get("/api/tasks/today", headers=h).json()
    overs = [x for x in d3["timeline"] if x["type"] == "overflow"]
    assert d3["summary"]["overflow"] > 0 and overs, d3["summary"]
    assert "明日优先" in (overs[0].get("note") or "")
    passed.append(f"5. 溢出区 OK（溢出 {d3['summary']['overflow']} 条，含改期建议）")

    # 6) 溢出任务「明日优先」→ 今日不再占位
    oid = overs[0]["task"]["id"]
    c.post(f"/api/tasks/{oid}/feedback", headers=h, json={"ai_urgency": 5, "ai_importance": 4, "due_time": d3["date"]})
    from datetime import date, timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    c.post(f"/api/tasks/{oid}/feedback", headers=h, json={"due_time": tomorrow})
    d4 = c.get("/api/tasks/today", headers=h).json()
    assert all(x["task"]["id"] != oid for x in d4["timeline"]), "改期后仍在今日视图"
    passed.append("6. 明日优先/改期 → 今日视图移除（planned_for）OK")

    # 7) 早宣一键入池（手册 1.5 与早宣的关系）
    r = c.post("/api/briefings/morning", headers=h, json={
        "tasks_raw": "上午核对发货清单；下午4点生产交班会", "ingest": True, "use_llm": False,
    })
    ing = r.json().get("ingested")
    assert ing and ing["created"] == 2, r.json()
    d5 = c.get("/api/tasks/today", headers=h).json()
    assert any("交班会" in x["title"] and x["bucket"] == "B0" for x in d5["timeline"])
    passed.append("7. 早宣稿一键入池，交班会识别为 B0 OK")

    # 8) 领导模式：他人/部门任务优先
    c.post("/api/tasks/ingest", headers=h, json={"items": [
        {"title": "个人重要紧急事", "estimated_hours": 1, "ai_importance": 5, "ai_urgency": 5, "ai_complexity": 1, "ai_impact_scope": "个人"},
        {"title": "部门协调杂事", "estimated_hours": 2, "ai_importance": 2, "ai_urgency": 2, "ai_impact_scope": "部门"},
    ]})
    plain = [x["title"] for x in c.get("/api/tasks/today", headers=h).json()["timeline"]]
    leader = [x["title"] for x in c.get("/api/tasks/today?leader_mode=true", headers=h).json()["timeline"]]
    assert plain.index("个人重要紧急事") < plain.index("部门协调杂事")
    assert leader.index("部门协调杂事") < leader.index("个人重要紧急事")
    passed.append("8. 领导模式排序反转 OK")

    # 9) 审计留痕
    from app.database import AuditLog, SessionLocal
    db = SessionLocal()
    actions = {a for (a,) in db.execute(__import__("sqlalchemy").text(
        "SELECT DISTINCT action FROM audit_logs"))}
    db.close()
    need = {"task.capture", "task.ingest", "task.status", "task.feedback", "briefing.morning"}
    assert need <= actions, f"缺审计: {need - actions}"
    passed.append("9. 审计留痕 5 类动作 OK")

    # 10) 晚总/周计划/周总结/结项/推送 审计补齐（本轮新增）
    c.post("/api/briefings/evening", headers=h, json={"done_raw": "完成周报", "issues_raw": "无", "tomorrow": "继续"})
    c.post("/api/briefings/weekly-plan", headers=h, json={"goals_raw": "本周完成GA图", "projects_raw": "泵站项目"})
    c.post("/api/briefings/weekly-summary", headers=h, json={"done_raw": "GA图已交", "issues_raw": "无"})
    c.post("/api/briefings/project-closure", headers=h, json={
        "project": "XX泵站", "overview": "按期交付", "results_raw": "合同额100万，按期交付",
    })
    r = c.post("/api/briefings/push", headers=h, json={"payload": {"任务名称": "测试推送"}, "kind": "task"})
    assert r.status_code == 200 and r.json().get("ok"), r.text
    db = SessionLocal()
    actions = {a for (a,) in db.execute(__import__("sqlalchemy").text(
        "SELECT DISTINCT action FROM audit_logs"))}
    db.close()
    need2 = {"briefing.evening", "briefing.weekly_plan", "briefing.weekly_summary",
             "briefing.project_closure", "briefing.push_jdy"}
    assert need2 <= actions, f"缺审计: {need2 - actions}"
    passed.append("10. 晚总/周计划/周总结/结项/推送 审计补齐 OK")

    # 11) 时间轴拖拽排序：/tasks/reorder 写 manual_order，同桶内手动顺序优先于评分
    # （同评分同桶才能体现手动顺序；跨桶拖拽按设计由桶优先级决定，B0 不可打乱）
    items = [
        {"title": "排序任务A", "estimated_hours": 1, "ai_urgency": 3, "ai_importance": 3},
        {"title": "排序任务B", "estimated_hours": 1, "ai_urgency": 3, "ai_importance": 3},
        {"title": "排序任务C", "estimated_hours": 1, "ai_urgency": 3, "ai_importance": 3},
    ]
    c.post("/api/tasks/ingest", headers=h, json={"items": items})
    tl = c.get("/api/tasks/today", headers=h).json()["timeline"]
    ids3 = [x["task"]["id"] for x in tl if x["title"].startswith("排序任务")]
    assert len(ids3) == 3, ids3
    rev = list(reversed(ids3))
    r = c.post("/api/tasks/reorder", headers=h, json={"ids": rev})
    assert r.json()["updated"] == 3, r.text
    tl2 = c.get("/api/tasks/today", headers=h).json()["timeline"]
    ids3_after = [x["task"]["id"] for x in tl2 if x["title"].startswith("排序任务")]
    assert ids3_after == rev, f"拖拽顺序未生效: {ids3_after} != {rev}"
    # 越权防护：不能排别人的任务
    r2 = c.post("/api/auth/dev-login", json={"name": "排序他人", "department": "外部"})
    h2 = {"Authorization": f"Bearer {r2.json()['token']}"}
    r = c.post("/api/tasks/reorder", headers=h2, json={"ids": rev})
    assert r.json()["updated"] == 0, "他人任务不可被排序"
    passed.append("11. 时间轴拖拽排序（manual_order 生效 + 越权隔离）OK")

    # 12) 简道云回写与同步（MOCK 模式）
    r = c.post("/api/tasks/sync-jdy", headers=h, json={})
    assert r.json()["mode"] == "mock" and r.json()["synced"] == 0, r.text
    # 带 jdy_data_id 的任务完成时触发回写（mock 成功）
    from app.database import TaskItem, SessionLocal as _SL
    db2 = _SL()
    uid = db2.execute(__import__("sqlalchemy").text("SELECT id FROM users WHERE name='核查员'")).scalar()
    db2.add(TaskItem(user_id=uid, title="简道云来源任务", jdy_data_id="jdy-row-001",
                     ai_dedup_key="jdy-row-001"))
    db2.commit()
    jid = db2.execute(__import__("sqlalchemy").text(
        "SELECT id FROM task_items WHERE jdy_data_id='jdy-row-001'")).scalar()
    db2.close()
    r = c.post(f"/api/tasks/{jid}/status", headers=h, json={"status": "已完成"})
    wb = r.json().get("jdy_writeback")
    assert wb and wb["ok"] and wb["mode"] == "mock", r.text
    db2 = _SL()
    actions = {a for (a,) in db2.execute(__import__("sqlalchemy").text(
        "SELECT DISTINCT action FROM audit_logs"))}
    db2.close()
    assert {"task.reorder", "task.sync_jdy", "task.jdy_writeback"} <= actions, actions
    passed.append("12. 简道云状态回写 + 同步接口 + 三类审计 OK")

print("\n".join(passed))
print(f"\n全部通过：{len(passed)} 项 + 迁移项")
