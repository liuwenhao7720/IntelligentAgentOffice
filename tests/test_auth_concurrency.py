# -*- coding: utf-8 -*-
"""登录与多用户并发集成测试（多 worker 真实服务）。

用法（在具备依赖的环境内）：
    python tests/test_auth_concurrency.py [--port 8123] [--workers 4]

自动完成：
  1. 以 N 个 uvicorn worker 启动独立实例（临时 SQLite 库，不影响生产数据）
  2. T1 并发同名首次登录：全部 200、同一 user_id、无 500（唯一约束竞态修复）
  3. T2 多用户并发登录：全部 200、id 唯一
  4. T3 令牌身份一致性：混合并发 /auth/me，无 401、无串号（跨 worker 校验）
  5. T4 伪造/篡改令牌 → 一律 401
  6. T5 过期令牌 → 401
  7. T6 越权钳制：非白名单申请 admin → staff；白名单 → admin
  8. T7 会话/数据隔离：A 的会话 B 不可见不可读；任务项目同样隔离
  9. T8 输入验证：空姓名/超长姓名/非法 role → 422
 10. T9 令牌唯一性：同一用户多次登录令牌互不相同且并行有效（多端在线）
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac as hmac_mod
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

SECRET = "test-secret-concurrency"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def forge_token(uid: int, exp: int, secret: str) -> str:
    """用测试密钥手工签发令牌（用于构造过期令牌等边界情形）。"""
    payload = json.dumps({"uid": uid, "iat": exp - 3600, "exp": exp, "nonce": "x"}, separators=(",", ":"))
    p64 = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(
        hmac_mod.new(secret.encode(), p64.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"vflo1.{p64}.{sig}"


async def wait_ready(base: str, timeout: float = 30.0) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=5) as c:
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                r = await c.get("/api/health")
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.3)
    raise RuntimeError("test server not ready")


async def login(c: httpx.AsyncClient, name: str, dept: str = "并发测试部", role: str = "staff") -> httpx.Response:
    return await c.post("/api/auth/dev-login", json={
        "name": name, "department": dept, "position": "工程师", "role": role,
    })


async def run_tests(base: str) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=30) as c:
        await wait_ready(base)

        print("T1 并发同名首次登录（唯一约束竞态）")
        rs = await asyncio.gather(*[login(c, "并发同名") for _ in range(16)])
        codes = [r.status_code for r in rs]
        ids = {r.json()["user"]["id"] for r in rs if r.status_code == 200}
        check("T1.1 16 并发同名登录全部 200", all(x == 200 for x in codes), f"codes={codes}")
        check("T1.2 全部指向同一 user_id", len(ids) == 1, f"ids={ids}")

        print("T2 多用户并发登录")
        rs = await asyncio.gather(*[login(c, f"用户{i:02d}") for i in range(20)])
        codes = [r.status_code for r in rs]
        ids = [r.json()["user"]["id"] for r in rs if r.status_code == 200]
        check("T2.1 20 用户并发登录全部 200", all(x == 200 for x in codes), f"codes={codes}")
        check("T2.2 user_id 全部唯一", len(set(ids)) == 20, f"unique={len(set(ids))}")

        print("T3 令牌身份一致性（混合并发 /auth/me，检验跨 worker 串号）")
        users = {}  # token -> expected name
        for i in range(10):
            r = await login(c, f"身份{i:02d}")
            assert r.status_code == 200
            users[r.json()["token"]] = r.json()["user"]["name"]

        async def me(token: str) -> tuple[int, str | None]:
            r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            return r.status_code, (r.json().get("name") if r.status_code == 200 else None)

        tasks = [(t, n) for t, n in users.items() for _ in range(10)]
        results = await asyncio.gather(*[me(t) for t, _ in tasks])
        bad_401 = sum(1 for code, _ in results if code != 200)
        wrong = [(tasks[i][1], name) for i, (code, name) in enumerate(results) if code == 200 and name != tasks[i][1]]
        check("T3.1 100 次 /auth/me 无 401", bad_401 == 0, f"401 次数={bad_401}")
        check("T3.2 无身份串号", not wrong, f"串号样本={wrong[:3]}")

        print("T4 伪造/篡改令牌")
        some_token = next(iter(users))
        p64 = some_token.split(".")[1]
        pad = "=" * (-len(p64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(p64 + pad))
        payload["uid"] = 99999  # 篡改 uid，不重签名
        tampered_p64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        tampered = f"vflo1.{tampered_p64}.{some_token.split('.')[2]}"
        for bad in [tampered, some_token[:-2] + "xx", "dev-token-1", "garbage"]:
            r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"})
            check(f"T4.x 无效令牌[{bad[:24]!r}…] → 401", r.status_code == 401, f"got {r.status_code}")
        r = await c.get("/api/auth/me")  # 无 Authorization 头
        check("T4.x 缺少令牌 → 401", r.status_code == 401, f"got {r.status_code}")

        print("T5 过期令牌")
        expired = forge_token(uid=1, exp=int(time.time()) - 10, secret=SECRET)
        r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
        check("T5.1 过期令牌 → 401", r.status_code == 401, f"got {r.status_code}")
        valid = forge_token(uid=1, exp=int(time.time()) + 3600, secret=SECRET)
        r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {valid}"})
        check("T5.2 正确签名的未过期令牌可验签(用户或不存在)", r.status_code in (200, 401), f"got {r.status_code}")

        print("T6 越权钳制")
        r = await login(c, "普通新人", role="admin")
        check("T6.1 非白名单申请 admin → staff", r.status_code == 200 and r.json()["user"]["role"] == "staff",
              f"got {r.status_code} {r.text[:80]}")
        r = await c.get("/api/admin/stats", headers={"Authorization": f"Bearer {r.json()['token']}"})
        check("T6.2 staff 访问管理接口 → 403", r.status_code == 403, f"got {r.status_code}")
        r = await login(c, "白名单管理员", role="admin")
        check("T6.3 白名单用户可获得 admin", r.status_code == 200 and r.json()["user"]["role"] == "admin",
              f"got {r.status_code} {r.text[:80]}")
        r = await login(c, "并发同名", role="admin")  # T1 已建 staff 用户
        check("T6.4 老用户登录不被升权", r.status_code == 200 and r.json()["user"]["role"] == "staff",
              f"got {r.text[:80]}")

        print("T7 会话与数据隔离")
        ra = await login(c, "隔离甲", dept="隔离部A")
        rb = await login(c, "隔离乙", dept="隔离部B")
        ta, tb = ra.json()["token"], rb.json()["token"]
        ha, hb = {"Authorization": f"Bearer {ta}"}, {"Authorization": f"Bearer {tb}"}
        r = await c.post("/api/sessions", headers=ha, json={"title": "甲的机密会话"})
        sid_a = r.json()["id"]
        r = await c.post("/api/sessions", headers=hb, json={"title": "乙的机密会话"})
        sid_b = r.json()["id"]
        r = await c.get(f"/api/sessions/{sid_a}", headers=hb)
        check("T7.1 乙读甲的会话 → 404", r.status_code == 404, f"got {r.status_code}")
        r = await c.get("/api/sessions", headers=ha)
        mine_a = [s["id"] for s in r.json()]
        check("T7.2 甲的列表不含乙的会话", sid_b not in mine_a and sid_a in mine_a)
        r = await c.post(f"/api/sessions/{sid_a}/generate", headers=hb, json={})
        check("T7.3 乙操作甲的会话生成 → 404", r.status_code == 404, f"got {r.status_code}")
        r = await c.post(f"/api/sessions/{sid_a}/finalize", headers=hb, json={"content": "篡改"})
        check("T7.4 乙定稿甲的会话 → 404", r.status_code == 404, f"got {r.status_code}")
        # 任务项目隔离
        r = await c.post("/api/task-projects", headers=ha, json={"name": "甲的项目"})
        code_a = r.json()["code"]
        r = await c.get(f"/api/task-projects/{code_a}", headers=hb)
        check("T7.5 乙读甲的任务项目 → 404", r.status_code == 404, f"got {r.status_code}")
        r = await c.get("/api/task-projects", headers=hb)
        check("T7.6 乙的项目列表为空", r.json() == [], f"got {len(r.json())} 条")

        print("T8 输入验证")
        r = await c.post("/api/auth/dev-login", json={"name": "", "department": "x"})
        check("T8.1 空姓名 → 422", r.status_code == 422, f"got {r.status_code}")
        r = await c.post("/api/auth/dev-login", json={"name": "x" * 100, "department": "x"})
        check("T8.2 超长姓名 → 422", r.status_code == 422, f"got {r.status_code}")
        r = await c.post("/api/auth/dev-login", json={"name": "ok", "role": "superadmin"})
        check("T8.3 非法 role → 422", r.status_code == 422, f"got {r.status_code}")
        r = await c.post("/api/auth/dev-login", content=b"{bad json", headers={"Content-Type": "application/json"})
        check("T8.4 非法 JSON → 422", r.status_code == 422, f"got {r.status_code}")

        print("T9 令牌唯一性与多端并行")
        r1 = await login(c, "多端用户")
        r2 = await login(c, "多端用户")
        t1, t2 = r1.json()["token"], r2.json()["token"]
        check("T9.1 同用户两次登录令牌不同", t1 != t2)
        r1 = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {t1}"})
        r2 = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {t2}"})
        check("T9.2 两个令牌并行有效且身份一致",
              r1.status_code == 200 and r2.status_code == 200
              and r1.json()["name"] == r2.json()["name"] == "多端用户")

        print("T10 并发混合读写压测（20 用户 × 各自创建会话+列表）")
        toks = []
        for i in range(20):
            r = await login(c, f"压测{i:02d}")
            toks.append((r.json()["token"], f"压测{i:02d}"))

        async def workload(token: str, name: str) -> str:
            h = {"Authorization": f"Bearer {token}"}
            r = await c.post("/api/sessions", headers=h, json={"title": f"{name}的会话"})
            if r.status_code != 200:
                return f"create {r.status_code}"
            r = await c.get("/api/sessions", headers=h)
            titles = [s["title"] for s in r.json()]
            if f"{name}的会话" not in titles:
                return "own session missing"
            if any(not t.startswith(name) and "压测" in t for t in titles):
                return f"cross-talk: {titles}"
            return "ok"

        outs = await asyncio.gather(*[workload(t, n) for t, n in toks])
        bad = [o for o in outs if o != "ok"]
        check("T10.1 20 用户并发读写全部成功且无串数据", not bad, f"bad={bad[:5]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--target", default="", help="直接测试已运行实例（不启动新服务）")
    args = ap.parse_args()

    if args.target:
        asyncio.run(run_tests(args.target.rstrip("/")))
    else:
        tmpdir = tempfile.mkdtemp(prefix="vflo-test-")
        env = dict(os.environ)
        env.update({
            "DATABASE_URL": f"sqlite:///{tmpdir}/test.db",
            "SECRET_KEY": SECRET,
            "MOCK_LLM": "1",
            "ENABLE_DEV_LOGIN": "1",
            "DEV_ADMIN_USERS": "白名单管理员",
            "TOKEN_TTL_HOURS": "24",
        })
        log_path = Path(tmpdir) / "server.log"
        log_fp = open(log_path, "w")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(args.port),
             "--workers", str(args.workers)],
            cwd=str(ROOT), env=env,
            stdout=log_fp, stderr=log_fp,
        )
        print(f"测试实例: 127.0.0.1:{args.port} workers={args.workers} db={tmpdir}/test.db")
        try:
            asyncio.run(run_tests(f"http://127.0.0.1:{args.port}"))
        except Exception:
            print("!! 测试中断，测试实例日志中的错误行：")
            try:
                import re
                lines = log_path.read_text().splitlines()
                for i, ln in enumerate(lines):
                    if re.search(r"(?i)error|traceback|exception|fatal|panic", ln):
                        print("\n".join(lines[max(0, i - 2):i + 20]))
                        print("...")
            except Exception:
                pass
            raise
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("")
    print(f"===== 结果: {len(PASSED)} PASS, {len(FAILED)} FAIL =====")
    if FAILED:
        print("失败项:", ", ".join(FAILED))
        return 1
    print("ALL CONCURRENCY TESTS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
