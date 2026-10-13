# -*- coding: utf-8 -*-
"""RBAC 角色权限 / 登录隔离 / 企微扫码登录框架 专项测试。

直接运行：python tests/test_rbac.py
- 进程内 TestClient，独立临时 SQLite，MOCK_LLM=1
- 企微 OAuth 通过 monkeypatch WeComClient 完成，无需真实网络/凭证
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="vflo_rbac_test_"))
os.environ["MOCK_LLM"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["DEV_ADMIN_USERS"] = "院长"  # 初始 admin 唯一入口（白名单）
os.environ["WECOM_CORP_ID"] = "ww-test-corp"
os.environ["WECOM_AGENT_ID"] = "1000002"
os.environ["WECOM_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import wecom_auth  # noqa: E402
from app.services import wecom as wecom_svc  # noqa: E402

FAILED: list[str] = []


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


def admin_patch(client: TestClient, h: dict, uid: int, **patch) -> tuple[int, dict]:
    r = client.patch(f"/api/v1/admin/users/{uid}", headers=h, json=patch)
    return r.status_code, (r.json() if r.text else {})


def test_rbac(client: TestClient) -> None:
    print("[rbac] 角色权限矩阵")
    h_admin = login(client, "院长", role="admin")   # 白名单 → admin
    h_staff = login(client, "员工甲")

    # staff：部门统计 403 / 用户管理 403 / 出口终审 403
    r = client.get("/api/v1/briefings/stats", headers=h_staff)
    check("staff 访问部门推送统计 403", r.status_code == 403, r.status_code)
    r = client.get("/api/v1/admin/users", headers=h_staff)
    check("staff 访问用户管理 403", r.status_code == 403, r.status_code)

    # admin 用户列表
    r = client.get("/api/v1/admin/users", headers=h_admin)
    check("admin 用户列表 200", r.status_code == 200, r.text)
    users = {u["name"]: u for u in r.json()}
    uid_staff = users["员工甲"]["id"]

    # admin 提拔 员工甲 为 manager
    code, body = admin_patch(client, h_admin, uid_staff, role="manager")
    check("admin 改角色 staff→manager", code == 200 and body.get("role") == "manager", (code, body))

    # manager 可访问部门统计，且被强制锁定本部门
    r = client.get("/api/v1/briefings/stats", headers=h_staff)
    check("manager 访问部门统计 200", r.status_code == 200, r.text)
    check("manager 强制本部门", r.json().get("department") == "项目部", r.json())
    r = client.get("/api/v1/briefings/stats?department=商务部", headers=h_staff)
    check("manager 指定他部门被忽略", r.json().get("department") == "项目部", r.json())

    # manager 仍无出口终审权；compliance 有
    r = client.post("/api/v1/export-checks", headers=h_admin, json={
        "customer_name": "RBAC Co", "country": "伊朗", "end_user": "民用厂",
        "end_use": "民用", "product_desc": "普通离心泵"})
    case_no = r.json()["case_no"]
    r = client.post(f"/api/v1/export-checks/{case_no}/review", headers=h_staff,
                    json={"action": "approve", "note": "x"})
    check("manager 无出口终审权 403", r.status_code == 403, r.status_code)

    # 设立合规官并终审（不能自审：单子是 admin 建的，合规官可审）
    h_comp = login(client, "合规官丙", dept="威标部")
    users = {u["name"]: u for u in client.get("/api/v1/admin/users", headers=h_admin).json()}
    admin_patch(client, h_admin, users["合规官丙"]["id"], role="compliance")
    r = client.post(f"/api/v1/export-checks/{case_no}/review", headers=h_comp,
                    json={"action": "approve", "note": "合规放行"})
    check("compliance 终审 200", r.status_code == 200, r.text)
    check("终审签字留痕", r.json().get("reviewed_by") == "合规官丙", r.json())

    # 合规官不能看全局管理看板
    r = client.get("/api/v1/admin/stats", headers=h_comp)
    check("compliance 无全局看板 403", r.status_code == 403, r.status_code)

    # 防误锁：admin 不能改自己角色/停用自己（自降级永远禁止，即使还有其他 admin）
    uid_admin = users["院长"]["id"]
    code, body = admin_patch(client, h_admin, uid_admin, role="staff")
    check("admin 自降级 422", code == 422, (code, body))
    code, body = admin_patch(client, h_admin, uid_admin, status="disabled")
    check("admin 自停用 422", code == 422, (code, body))
    # 第二名 admin（合规官丙已提拔）可降级院长；降级后院长 token 立即失去管理权
    uid_comp = users["合规官丙"]["id"]
    code, _ = admin_patch(client, h_admin, uid_comp, role="admin")
    check("提拔第二 admin", code == 200, code)
    code, _ = admin_patch(client, h_comp, uid_admin, role="staff")
    check("其他 admin 可降级院长", code == 200, code)
    r = client.get("/api/v1/admin/users", headers=h_admin)
    check("降级后 token 立即失权 403", r.status_code == 403, r.status_code)
    code, _ = admin_patch(client, h_comp, uid_admin, role="admin")
    check("还原院长 admin", code == 200, code)

    # 登录隔离：停用立即生效（token 无吊销表，每请求查库）
    h_target = login(client, "停用丁")
    users = {u["name"]: u for u in client.get("/api/v1/admin/users", headers=h_admin).json()}
    admin_patch(client, h_admin, users["停用丁"]["id"], status="disabled")
    r = client.get("/api/v1/auth/me", headers=h_target)
    check("停用后 token 立即 401", r.status_code == 401, r.status_code)
    admin_patch(client, h_admin, users["停用丁"]["id"], status="active")
    r = client.get("/api/v1/auth/me", headers=h_target)
    check("启用后恢复 200", r.status_code == 200, r.status_code)


def test_wecom(client: TestClient) -> None:
    print("[wecom] 扫码登录框架")
    # config：凭证齐备 → 启用
    r = client.get("/api/v1/auth/wecom/config")
    check("config 启用", r.status_code == 200 and r.json()["wecom_enabled"] is True, r.json())

    # qr-url：参数齐全 + state 签名结构
    r = client.get("/api/v1/auth/wecom/qr-url")
    check("qr-url 200", r.status_code == 200, r.text)
    url, state = r.json()["url"], r.json()["state"]
    check("qr-url 指向官方授权页", url.startswith("https://open.work.weixin.qq.com/wwopen/sso/qrConnect?"), url[:80])
    check("qr-url 含 corp/agent/redirect/state",
          "appid=ww-test-corp" in url and "agentid=1000002" in url
          and "redirect_uri=" in url and "state=" in url, url)
    check("state 签验通过", wecom_auth.verify_state(state))
    check("state 篡改拒绝", not wecom_auth.verify_state(state + "x"))
    # 有效签名 + 过期时间戳 → 仍拒绝（测的是 TTL，不是签名）
    import time as _t
    old_ts = str(int(_t.time()) - 3600)
    expired = f"wc1.{old_ts}.abc123.{wecom_auth._state_sig(old_ts, 'abc123')}"
    check("state 过期拒绝", not wecom_auth.verify_state(expired))

    # callback：state 无效 → 400；缺 code → 400
    r = client.get("/api/v1/auth/wecom/callback?code=x&state=bad", follow_redirects=False)
    check("坏 state 400", r.status_code == 400, r.status_code)
    r = client.get(f"/api/v1/auth/wecom/callback?state={state}", follow_redirects=False)
    check("缺 code 400", r.status_code == 400, r.status_code)

    # monkeypatch 企微客户端：模拟扫码成功（新用户自动建号）
    class FakeClient:
        def get_user_id(self, code): return "WcUser001"
        def get_user_detail(self, userid): return {"name": "企微用户", "department_names": "商务部"}
    wecom_auth.WeComClient = lambda: FakeClient()  # type: ignore[assignment]

    state2 = wecom_auth.issue_state()
    r = client.get(f"/api/v1/auth/wecom/callback?code=real-code&state={state2}",
                   follow_redirects=False)
    check("callback 302", r.status_code == 302, r.status_code)
    loc = r.headers.get("location", "")
    check("302 带 wecom_token", "/?wecom_token=" in loc, loc)
    token = loc.split("wecom_token=", 1)[1]
    h_wc = {"Authorization": f"Bearer {token}"}
    r = client.get("/api/v1/auth/me", headers=h_wc)
    check("扫码 token 可用", r.status_code == 200 and r.json()["name"] == "企微用户", r.text)
    check("企微建号默认 staff", r.json()["role"] == "staff", r.json())
    check("企微部门照录", r.json()["department"] == "商务部", r.json())

    # 再次扫码：复用同一账号（不产生重复用户）
    users_before = len(client.get("/api/v1/admin/users",
                                  headers=login(client, "院长", role="admin")).json())
    state3 = wecom_auth.issue_state()
    client.get(f"/api/v1/auth/wecom/callback?code=code2&state={state3}", follow_redirects=False)
    users_after = len(client.get("/api/v1/admin/users",
                                 headers=login(client, "院长", role="admin")).json())
    check("老用户复用不重复建号", users_before == users_after, (users_before, users_after))

    # 停用账号扫码 → 403
    h_admin2 = login(client, "院长", role="admin")
    users = {u["name"]: u for u in client.get("/api/v1/admin/users", headers=h_admin2).json()}
    admin_patch(client, h_admin2, users["企微用户"]["id"], status="disabled")
    state4 = wecom_auth.issue_state()
    r = client.get(f"/api/v1/auth/wecom/callback?code=code3&state={state4}",
                   follow_redirects=False)
    check("停用账号扫码 403", r.status_code == 403, r.status_code)

    # 网络异常 → 503 降级文案
    class DownClient:
        def get_user_id(self, code): raise wecom_svc.WeComError("企微接口不可达：ConnectError")
    wecom_auth.WeComClient = lambda: DownClient()  # type: ignore[assignment]
    state5 = wecom_auth.issue_state()
    r = client.get(f"/api/v1/auth/wecom/callback?code=c&state={state5}", follow_redirects=False)
    check("网络异常 503 降级", r.status_code == 503 and "开发登录" in str(r.json()), r.status_code)

    # 未配置凭证 → config/qr-url 降级（进程内无法改 lru_cache，验证 is_wecom_configured 逻辑）
    check("is_wecom_configured 识别凭证", wecom_svc.is_wecom_configured() is True)


def main() -> int:
    with TestClient(app) as client:
        test_rbac(client)
        test_wecom(client)
    if FAILED:
        print(f"\nTEST_RBAC FAILED: {len(FAILED)} 项 -> {FAILED}")
        return 1
    print("\nTEST_RBAC OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
