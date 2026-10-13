# -*- coding: utf-8 -*-
"""E2E 真实链路测试：登录 → 选场景 → 建会话 → 生成 → 定稿 → 归档。

对「已启动的真实服务 + 真实模型 Key」跑 HTTP 级全链路，
与 tests/smoke.py（进程内 TestClient、允许 mock）互补。

用法：
    # 附着已启动服务（默认；也可用环境变量 E2E_BASE_URL）
    python tests/e2e_real.py --base-url http://127.0.0.1:8000

    # 自拉起临时实例：临时 SQLite 库 + 继承当前环境的真实 Key，跑完自动销毁
    python tests/e2e_real.py --spawn [--port 8124]

    # 发布门禁：要求必须真实模型，目标为 mock 时判失败（退出码 2）
    python tests/e2e_real.py --require-real

跳过规则：目标服务 /api/health 返回 mock_llm=true 时，默认打印 SKIP 并退出 0；
--require-real 下退出 2。退出码：0=全过或按规则跳过；1=有用例失败；2=require-real 检出 mock。
degraded=true（主模型失败自动降级备援）默认仅告警，--strict-degraded 时判失败。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []

# 真实 LLM 生成最长等待（服务端 REQUEST_TIMEOUT 默认 120s，留足余量）
GENERATE_TIMEOUT = 180.0

# 主链用 staff 账号即可（不依赖 DEV_ADMIN_USERS 白名单）
E2E_USER = {"name": "E2E巡检员", "department": "质量部", "position": "巡检工程师", "role": "staff"}

# SC-PRJ-001 必填变量（customer 选填）：与 app/seed/scenarios.py 对齐
E2E_VARIABLES = {
    "project_name": "E2E巡检-测试泵站",
    "week_progress": "完成GA图提交；泵组水力性能复核通过",
    "risks": "客户延迟确认材质，存在交付风险",
    "next_plan": "跟进材质确认，责任人王工，周五前闭环",
    "customer": "OOO E2E Test",
}


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def wait_ready(base: str, timeout: float = 30.0) -> None:
    t0 = time.time()
    with httpx.Client(base_url=base, timeout=5) as c:
        while time.time() - t0 < timeout:
            try:
                r = c.get("/api/health")
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
    raise RuntimeError(f"目标服务未就绪: {base}")


def run_e2e(base: str, *, require_real: bool, strict_degraded: bool) -> str:
    """返回 'done'（全链执行完毕）或 'skipped'（目标为 mock，按规则跳过）。"""
    t_start = time.time()
    wait_ready(base)

    with httpx.Client(base_url=base, timeout=30) as c:
        # ---------- E0 健康检查 + mock 探测 ----------
        print("E0 健康检查与 mock 探测")
        r = c.get("/api/health")
        check("E0.1 /api/health → 200", r.status_code == 200, f"got {r.status_code}")
        if r.status_code != 200:
            return "done"
        health = r.json()
        is_mock = bool(health.get("mock_llm"))
        print(f"      db={health.get('db')} database={health.get('database')} mock_llm={is_mock}")
        if is_mock:
            print("  [SKIP] 目标服务处于 mock_llm 模式（MOCK_LLM 强制 mock 或未配置任何模型 Key），"
                  "E2E 真实链路跳过")
            return "skipped"

        # ---------- E1 登录 ----------
        print("E1 登录（dev-login，staff 即可，不依赖 admin 白名单）")
        r = c.post("/api/auth/dev-login", json=E2E_USER)
        if r.status_code == 403:
            check("E1.1 dev-login 可用", False,
                  "开发登录已关闭（ENABLE_DEV_LOGIN=0），E2E 无法登录；请开启或改用企微 OAuth 账号")
            return "done"
        check("E1.1 dev-login → 200", r.status_code == 200, f"got {r.status_code} {r.text[:120]}")
        if r.status_code != 200:
            return "done"
        token = r.json()["token"]
        check("E1.2 返回非空 token", bool(token))
        h = {"Authorization": f"Bearer {token}"}
        r = c.get("/api/auth/me", headers=h)
        check("E1.3 /auth/me 身份一致", r.status_code == 200 and r.json().get("name") == E2E_USER["name"],
              f"got {r.status_code} {r.text[:120]}")
        r = c.post("/api/auth/dev-login", json={**E2E_USER, "name": "   "})
        check("E1.4 负向：空白姓名 → 422", r.status_code == 422, f"got {r.status_code}")

        # ---------- E2 选场景 ----------
        print("E2 选场景（SC-PRJ-001 项目周报）")
        r = c.get("/api/scenarios", headers=h)
        check("E2.1 /scenarios → 200", r.status_code == 200, f"got {r.status_code}")
        target = next((s for s in r.json() if s.get("code") == "SC-PRJ-001"), None) if r.status_code == 200 else None
        check("E2.2 场景卡含 SC-PRJ-001", target is not None)
        if not target:
            return "done"
        r = c.get(f"/api/scenarios/{target['id']}", headers=h)
        check("E2.3 场景详情 prompt_template 含 {{project_name}}",
              r.status_code == 200 and "{{project_name}}" in r.json().get("prompt_template", ""))

        # ---------- E3 建会话 ----------
        print("E3 建会话（完整必填变量）")
        r = c.post("/api/sessions", headers=h, json={
            "scenario_id": target["id"],
            "variables": E2E_VARIABLES,
        })
        check("E3.1 POST /sessions → 200", r.status_code == 200, f"got {r.status_code} {r.text[:120]}")
        if r.status_code != 200:
            return "done"
        sess = r.json()
        sid = sess["id"]
        check("E3.2 标题默认取场景名", sess.get("title") == target["title"], f"got {sess.get('title')!r}")
        check("E3.3 variables 回显 project_name",
              sess.get("variables", {}).get("project_name") == E2E_VARIABLES["project_name"])

        # ---------- E4 生成（真实 LLM） ----------
        print("E4 生成（真实 LLM，最长等待 180s）")
        t0 = time.time()
        r = c.post(f"/api/sessions/{sid}/generate", headers=h, json={}, timeout=GENERATE_TIMEOUT)
        wall = time.time() - t0
        check("E4.1 generate → 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
        gen = r.json() if r.status_code == 200 else {}
        if r.status_code == 200:
            print(f"      provider={gen.get('provider')} model={gen.get('model')} "
                  f"tokens={gen.get('tokens_in')}/{gen.get('tokens_out')} wall={wall:.1f}s "
                  f"degraded={gen.get('degraded')}")
            text = gen.get("text") or ""
            check("E4.2 provider 非 mock（真实模型出稿）", gen.get("provider") not in (None, "mock"),
                  f"provider={gen.get('provider')!r}")
            check("E4.3 正文非空且不含 MOCK 占位标记", bool(text.strip()) and "【MOCK" not in text)
            check("E4.4 tokens_in/tokens_out 均 > 0",
                  (gen.get("tokens_in") or 0) > 0 and (gen.get("tokens_out") or 0) > 0,
                  f"tokens={gen.get('tokens_in')}/{gen.get('tokens_out')}")
            check("E4.5 普通场景 model_locked=False", gen.get("model_locked") is False)
            if gen.get("degraded"):
                msg = "主模型失败已自动降级备援（产品行为）"
                if strict_degraded:
                    check("E4.6 degraded=false（--strict-degraded）", False, msg)
                else:
                    print(f"  [WARN] degraded=true：{msg}（--strict-degraded 可判失败）")

        # E4n 负向：缺必填变量的会话直接生成 → 422 且返回 missing 清单
        r = c.post("/api/sessions", headers=h, json={
            "scenario_id": target["id"],
            "variables": {"project_name": "缺变量负向用例"},
        })
        neg_sid = r.json()["id"] if r.status_code == 200 else None
        r = c.post(f"/api/sessions/{neg_sid}/generate", headers=h, json={}) if neg_sid else None
        check("E4.7 负向：缺必填变量生成 → 422", r is not None and r.status_code == 422,
              f"got {r.status_code if r else 'no-session'}")
        missing_ok = False
        if r is not None and r.status_code == 422:
            missing = (r.json().get("missing") or [])
            missing_ok = any(m.get("key") == "week_progress" for m in missing)
        check("E4.8 422 响应含 missing 清单（week_progress）", missing_ok)

        # ---------- E5 定稿 ----------
        print("E5 定稿（AI 初稿 + 人工补充 → diff 落库）")
        final_text = (gen.get("text") or "") + "\n\n（E2E 定稿补充：请王工在周五前书面确认材质。）"
        if gen:
            r = c.post(f"/api/sessions/{sid}/finalize", headers=h, json={"content": final_text})
            check("E5.1 finalize → 200", r.status_code == 200, f"got {r.status_code} {r.text[:120]}")
            fin = r.json() if r.status_code == 200 else {}
            check("E5.2 返回 diff_summary 与 edit_ratio",
                  bool(fin.get("diff_summary")) and fin.get("edit_ratio") is not None)
            r = c.get(f"/api/sessions/{sid}/diffs", headers=h)
            diffs = r.json() if r.status_code == 200 else []
            check("E5.3 GET diffs ≥ 1 条", len(diffs) >= 1, f"got {len(diffs)}")
            check("E5.4 diff 的 final_text 与定稿一致",
                  bool(diffs) and diffs[-1].get("final_text") == final_text)
        else:
            for n in ("E5.1 finalize → 200", "E5.2 返回 diff_summary 与 edit_ratio",
                      "E5.3 GET diffs ≥ 1 条", "E5.4 diff 的 final_text 与定稿一致"):
                check(n, False, "生成失败，定稿链路无法继续")

        # E5n 负向：未生成先定稿 → 422（另起全新空会话，不消耗 LLM）
        r = c.post("/api/sessions", headers=h, json={"title": "E2E-负向-未定稿"})
        empty_sid = r.json()["id"] if r.status_code == 200 else None
        r = c.post(f"/api/sessions/{empty_sid}/finalize", headers=h,
                   json={"content": "抢跑定稿"}) if empty_sid else None
        check("E5.5 负向：未生成先定稿 → 422", r is not None and r.status_code == 422,
              f"got {r.status_code if r else 'no-session'}")

        # ---------- E6 归档（知产库） ----------
        print("E6 归档（五步法：定稿再归档）")
        if gen:
            r = c.post("/api/assets", headers=h, json={
                "session_id": sid, "title": "E2E巡检-测试泵站周报", "content": final_text,
                "visibility": "private", "tags": ["E2E", "SC-PRJ-001"],
            })
            check("E6.1 POST /assets → 200", r.status_code == 200, f"got {r.status_code} {r.text[:120]}")
            asset = r.json() if r.status_code == 200 else {}
            check("E6.2 资产回显 session_id 关联", asset.get("session_id") == sid)
            r = c.get("/api/assets", headers=h, params={"scope": "mine", "q": "E2E巡检"})
            check("E6.3 /assets?scope=mine 可检索到归档资产",
                  r.status_code == 200 and any(a.get("id") == asset.get("id") for a in r.json()),
                  f"got {r.status_code}")
        else:
            for n in ("E6.1 POST /assets → 200", "E6.2 资产回显 session_id 关联",
                      "E6.3 /assets?scope=mine 可检索到归档资产"):
                check(n, False, "生成失败，归档链路无法继续")

        # E6n 负向：未定稿先归档 → 422（用 E4n 的缺变量会话，status=draft，不消耗 LLM）
        if neg_sid:
            r = c.post("/api/assets", headers=h, json={
                "session_id": neg_sid, "title": "E2E-负向-未定稿归档", "content": "抢跑归档",
            })
            check("E6.4 负向：未定稿先归档 → 422（五步法守卫）", r.status_code == 422,
                  f"got {r.status_code} {r.text[:120]}")

    print(f"\n主链耗时 {time.time() - t_start:.1f}s")
    return "done"


def spawn_server(port: int):
    """自拉起临时实例：临时 SQLite 库 + 继承当前环境真实 Key。返回 (proc, log_path, tmpdir)。"""
    tmpdir = tempfile.mkdtemp(prefix="vflo-e2e-")
    env = dict(os.environ)
    env.update({
        "DATABASE_URL": f"sqlite:///{tmpdir}/e2e.db",
        "SECRET_KEY": env.get("SECRET_KEY", "e2e-spawn-secret"),
        "ENABLE_DEV_LOGIN": "1",
        # 不强制 MOCK_LLM：继承调用方环境；若外部环境强制 mock，E0 会按规则 SKIP
    })
    log_path = Path(tmpdir) / "server.log"
    log_fp = open(log_path, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
        cwd=str(ROOT), env=env,
        stdout=log_fp, stderr=log_fp,
    )
    print(f"E2E 临时实例: 127.0.0.1:{port} db={tmpdir}/e2e.db log={log_path}")
    return proc, log_path, log_fp


def dump_server_log(log_path: Path) -> None:
    print("!! 临时实例日志中的错误行：")
    try:
        lines = log_path.read_text().splitlines()
        for i, ln in enumerate(lines):
            if re.search(r"(?i)error|traceback|exception|fatal", ln):
                print("\n".join(lines[max(0, i - 2):i + 20]))
                print("...")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="E2E 真实链路：登录→建会话→生成→定稿→归档")
    ap.add_argument("--base-url", default=os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000"),
                    help="已启动服务地址（默认 env E2E_BASE_URL 或 http://127.0.0.1:8000）")
    ap.add_argument("--spawn", action="store_true", help="自拉起临时实例（临时库，跑完销毁）")
    ap.add_argument("--port", type=int, default=8124, help="--spawn 实例端口")
    ap.add_argument("--require-real", action="store_true",
                    help="目标为 mock 时不跳过而判失败（退出码 2），供发布门禁使用")
    ap.add_argument("--strict-degraded", action="store_true", help="degraded=true 判失败（默认仅告警）")
    args = ap.parse_args()

    proc = log_fp = None
    log_path = None
    try:
        if args.spawn:
            proc, log_path, log_fp = spawn_server(args.port)
            base = f"http://127.0.0.1:{args.port}"
        else:
            base = args.base_url.rstrip("/")
        print(f"E2E 目标: {base} require_real={args.require_real} strict_degraded={args.strict_degraded}")
        outcome = run_e2e(base, require_real=args.require_real, strict_degraded=args.strict_degraded)
    except Exception:
        if log_path:
            dump_server_log(log_path)
        raise
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if log_fp:
            log_fp.close()

    if outcome == "skipped":
        if args.require_real:
            print("\n===== 结果: REQUIRE-REAL 失败——目标服务处于 mock_llm 模式 =====")
            return 2
        print("\n===== 结果: SKIPPED（mock_llm 模式，按规则跳过） =====")
        return 0

    print("")
    print(f"===== 结果: {len(PASSED)} PASS, {len(FAILED)} FAIL =====")
    if FAILED:
        print("失败项:", ", ".join(FAILED))
        return 1
    print("ALL E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
