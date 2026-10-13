# -*- coding: utf-8 -*-
"""简道云单向拉取同步（本地镜像）专项测试。

直接运行：python tests/test_jdy_sync.py
- 进程内 TestClient + 独立临时 SQLite
- monkeypatch jdy.query_form / list_widgets 造假数据，全程无真实网络
- 覆盖：upsert 新建/更新、prune 删除消失行、截断跳过 prune、同步日志、
  API 读取/详情/权限、mock 降级
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="vflo_jdy_test_"))
os.environ["MOCK_LLM"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["DEV_ADMIN_USERS"] = "管理员甲"
# 配上假凭证使 jdy.mock=False（query_form/list_widgets 会被 monkeypatch，不出网）
os.environ["JDY_APP_ID"] = "fake-app"
os.environ["JDY_API_KEY"] = "fake-key"
os.environ["JDY_ENTRY_TASK"] = "entry-task-1"
os.environ["JDY_ENTRY_KNOWLEDGE"] = "entry-knowledge-1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.jdy import jdy  # noqa: E402
from app.services import jdy_sync  # noqa: E402
from app.services.task_agent import JDY_FIELD_MAP  # noqa: E402

FAILED: list[str] = []

W_TITLE = JDY_FIELD_MAP["title"]
W_STATUS = JDY_FIELD_MAP["status"]
W_OWNER = JDY_FIELD_MAP["owner"]
W_DEPT = JDY_FIELD_MAP["dept"]
W_DUE = JDY_FIELD_MAP["due_time"]


def check(name: str, cond: bool, detail: object = "") -> None:
    if cond:
        print(f"  ok  {name}")
    else:
        FAILED.append(name)
        print(f" FAIL {name} :: {detail}")


def make_task_row(i: int, title: str, status: str = "进行中") -> dict:
    return {
        "_id": f"task-{i}",
        W_TITLE: title,
        W_STATUS: status,
        W_OWNER: [{"name": "张三"}],
        W_DEPT: [{"name": "项目部"}],
        W_DUE: "2026-10-20T00:00:00.000Z",
    }


# 可控的拉取桩
_STUB = {"task": [], "knowledge": [], "truncated": False}


def fake_query_form(entry_id, fields=None, filter=None, limit=100, max_pages=5):  # noqa: A002
    kind = "task" if entry_id == "entry-task-1" else "knowledge"
    jdy.last_truncated = _STUB["truncated"]
    return list(_STUB[kind])


def fake_list_widgets(entry_id):
    if entry_id == "entry-knowledge-1":
        return {"_widget_k1": "文档标题", "_widget_k2": "所属部门", "_widget_k3": "提交时间"}
    return {}


def login(client: TestClient, name: str, dept: str = "项目部", role: str = "staff") -> dict:
    r = client.post("/api/v1/auth/dev-login",
                    json={"name": name, "department": dept, "position": "工程师", "role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def main() -> int:
    jdy.query_form = fake_query_form       # type: ignore[assignment]
    jdy.list_widgets = fake_list_widgets   # type: ignore[assignment]
    assert not jdy.mock, "假凭证下不应为 mock"

    with TestClient(app) as client:
        h_admin = login(client, "管理员甲", role="admin")
        h_staff = login(client, "员工乙")

        print("[sync] upsert / prune / 截断")
        _STUB["task"] = [make_task_row(1, "泵站周报"), make_task_row(2, "澄清函回复")]
        _STUB["knowledge"] = [{
            "_id": "kn-1", "_widget_k1": "俄罗斯项目经验", "_widget_k2": "项目部",
            "_widget_k3": "2026-10-01 10:00:00",
        }]
        r = client.post("/api/v1/jdy/sync", headers=h_admin)
        check("手动同步 200", r.status_code == 200, r.text)
        d = r.json()
        check("任务同步 2 条", d["entries"]["task"]["items"] == 2, d["entries"])
        check("知识库同步 1 条", d["entries"]["knowledge"]["items"] == 1, d["entries"])
        check("新建计数", d["entries"]["task"]["created"] == 2, d["entries"]["task"])

        # 再次同步：一条标题变更（更新）、一条消失（prune）、新增一条
        _STUB["task"] = [make_task_row(1, "泵站周报V2"), make_task_row(3, "新增任务")]
        r = client.post("/api/v1/jdy/sync", headers=h_admin)
        d = r.json()["entries"]["task"]
        check("更新 1 + 新建 1", d["updated"] == 1 and d["created"] == 1, d)
        check("prune 删除消失行 1", d["pruned"] == 1, d)

        # 超长字段钳制回归：负责人数组 join 后超列宽不应导致整批 INSERT 失败
        row9 = make_task_row(9, "超长负责人任务")
        row9[W_OWNER] = [{"name": f"员工{i:02d}"} for i in range(60)]
        _STUB["task"] = [make_task_row(1, "泵站周报V2"), make_task_row(3, "新增任务"), row9]
        r = client.post("/api/v1/jdy/sync", headers=h_admin)
        check("超长字段不炸", r.status_code == 200
              and r.json()["entries"]["task"]["status"] == "success", r.text[:200])
        r = client.get("/api/v1/jdy/data/task/task-9", headers=h_staff)
        check("owner 钳制到列宽", r.status_code == 200 and len(r.json()["owner"]) <= 120,
              len(r.json().get("owner", "")))

        # 截断时跳过 prune（保旧数据）
        _STUB["task"] = [make_task_row(1, "泵站周报V2")]  # 若 prune 会删掉 task-3
        _STUB["truncated"] = True
        r = client.post("/api/v1/jdy/sync", headers=h_admin)
        d = r.json()["entries"]["task"]
        check("截断跳过 prune", d["truncated"] is True and d["pruned"] == 0, d)
        r = client.get("/api/v1/jdy/data/task", headers=h_staff)
        check("截断后旧记录仍在", any(x["data_id"] == "task-3" for x in r.json()["items"]), r.json())
        _STUB["truncated"] = False

        print("[api] 镜像读取")
        r = client.get("/api/v1/jdy/overview", headers=h_staff)
        check("overview 200 全体可读", r.status_code == 200, r.text)
        forms = {f["kind"]: f for f in r.json()["forms"]}
        check("overview 计数", forms["task"]["records"] == 3 and forms["knowledge"]["records"] == 1, forms)
        check("overview 非 mock", r.json()["mock"] is False, r.json())

        r = client.get("/api/v1/jdy/data/task", headers=h_staff)
        items = r.json()["items"]
        check("任务列表投影", items and items[0]["title"] and "owner" in items[0], items[:1])
        t1 = next(x for x in items if x["data_id"] == "task-1")
        check("投影列正确（标题/部门/截止）",
              t1["title"] == "泵站周报V2" and t1["dept"] == "项目部" and "2026-10-20" in t1["due_time"], t1)

        r = client.get("/api/v1/jdy/data/task?q=周报", headers=h_staff)
        check("标题搜索", r.json()["total"] == 1, r.json())

        r = client.get("/api/v1/jdy/data/task/task-1", headers=h_staff)
        check("详情中文字段", r.status_code == 200 and "任务名称" in r.json()["fields"], r.json())
        check("详情字段值", r.json()["fields"].get("任务名称") == "泵站周报V2", r.json()["fields"])

        r = client.get("/api/v1/jdy/data/knowledge/kn-1", headers=h_staff)
        kf = r.json()["fields"]
        check("知识库标签映射（widget→中文）", kf.get("文档标题") == "俄罗斯项目经验", kf)

        print("[perm] 权限")
        r = client.post("/api/v1/jdy/sync", headers=h_staff)
        check("staff 手动同步 403", r.status_code == 403, r.status_code)
        r = client.get("/api/v1/jdy/sync/logs", headers=h_staff)
        check("staff 看日志 403", r.status_code == 403, r.status_code)
        r = client.get("/api/v1/jdy/sync/logs", headers=h_admin)
        check("admin 看日志 200", r.status_code == 200 and len(r.json()) >= 3, r.text)
        check("日志含状态与计数", all("status" in x and "items" in x for x in r.json()), r.json()[:1])
        r = client.get("/api/v1/jdy/data/unknown", headers=h_staff)
        check("非法 kind 422", r.status_code == 422, r.status_code)

        # manager 也可手动同步
        users = client.get("/api/v1/admin/users", headers=h_admin).json()
        uid_staff = next(u["id"] for u in users if u["name"] == "员工乙")
        client.patch(f"/api/v1/admin/users/{uid_staff}", headers=h_admin, json={"role": "manager"})
        r = client.post("/api/v1/jdy/sync", headers=h_staff)
        check("manager 手动同步 200", r.status_code == 200, r.text)

        print("[mock] 降级")
        real_mock = jdy.mock
        jdy.mock = True
        r = client.post("/api/v1/jdy/sync", headers=h_admin)
        check("mock 同步 skipped 不报错", r.status_code == 200 and
              all(e["status"] == "skipped" for e in r.json()["entries"].values()), r.json())
        r = client.get("/api/v1/jdy/overview", headers=h_staff)
        check("mock overview 有提示", r.json()["mock"] is True and r.json()["hint"], r.json())
        jdy.mock = real_mock

    if FAILED:
        print(f"\nTEST_JDY_SYNC FAILED: {len(FAILED)} 项 -> {FAILED}")
        return 1
    print("\nTEST_JDY_SYNC OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
