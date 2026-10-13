# -*- coding: utf-8 -*-
"""企业微信扫码登录路由（无鉴权端点；靠一次性 state + 官方 code 防护）。

- GET /auth/wecom/config    前端登录页形态：是否展示扫码入口 / 开发登录表单
- GET /auth/wecom/qr-url    生成带签名 state 的扫码授权链接（整页跳转用）
- GET /auth/wecom/callback  扫码回调：验 state → code 换 userid → 建号/复用 → 302 带 token 回首页

安全设计：
- state 为 HMAC 签名的一次性防 CSRF 凭证（10 分钟有效，串用到登录 token 的签名域之外）；
- code 只能由企微授权页签发且一次性有效；
- 未配置凭证 / 内网出网失败 → 503 友好降级，不影响开发登录。
"""
from __future__ import annotations

import hmac
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import issue_dev_token
from ..auth import dev_login_enabled
from ..config import get_settings
from ..database import AuditLog, User, get_db
from ..services.wecom import WeComClient, WeComError, build_qr_connect_url, is_wecom_configured

router = APIRouter()

_STATE_PREFIX = "wc1"
_STATE_TTL = 600  # 10 分钟


def _state_sig(ts: str, nonce: str) -> str:
    import hashlib
    import base64
    key = get_settings().secret_key.encode("utf-8")
    raw = f"{_STATE_PREFIX}.{ts}.{nonce}".encode("ascii")
    return base64.urlsafe_b64encode(
        hmac.new(key, raw, hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")


def issue_state() -> str:
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    return f"{_STATE_PREFIX}.{ts}.{nonce}.{_state_sig(ts, nonce)}"


def verify_state(state: str) -> bool:
    parts = (state or "").split(".")
    if len(parts) != 4 or parts[0] != _STATE_PREFIX:
        return False
    ts, nonce, sig = parts[1], parts[2], parts[3]
    if not hmac.compare_digest(sig, _state_sig(ts, nonce)):
        return False
    try:
        return 0 <= time.time() - int(ts) <= _STATE_TTL
    except ValueError:
        return False


@router.get("/auth/wecom/config")
def wecom_config():
    """登录页形态配置（无鉴权）：前端据此显隐扫码入口与开发登录表单。"""
    return {
        "wecom_enabled": is_wecom_configured(),
        "dev_login_enabled": dev_login_enabled(),
    }


@router.get("/auth/wecom/qr-url")
def wecom_qr_url():
    if not is_wecom_configured():
        raise HTTPException(503, "企业微信登录未启用或未配置凭证，请使用开发登录")
    state = issue_state()
    return {"url": build_qr_connect_url(state), "state": state}


@router.get("/auth/wecom/callback")
def wecom_callback(code: str = "", state: str = "", db: Session = Depends(get_db)):
    if not is_wecom_configured():
        raise HTTPException(503, "企业微信登录未启用或未配置凭证")
    if not verify_state(state):
        raise HTTPException(400, "登录状态无效或已过期，请重新扫码")
    if not code:
        raise HTTPException(400, "缺少授权 code")

    client = WeComClient()
    try:
        userid = client.get_user_id(code)
        detail = client.get_user_detail(userid)
    except WeComError as e:
        msg = str(e)
        if "不可达" in msg:
            raise HTTPException(503, "企业微信服务暂不可达（内网出网受限？），请改用开发登录")
        raise HTTPException(403, f"企业微信登录失败：{msg}")

    name = (detail.get("name") or userid)[:64]
    department = (detail.get("department_names") or "")[:64]

    user = db.execute(select(User).where(User.wecom_userid == userid)).scalar_one_or_none()
    if not user:
        user = User(
            wecom_userid=userid,
            name=name,
            department=department,
            position="",
            role="staff",  # 企微建号一律 staff；角色由管理员在「用户管理」分配
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # 并发扫码首次登录：另一请求已建号，回滚后重查
            db.rollback()
            user = db.execute(select(User).where(User.wecom_userid == userid)).scalar_one_or_none()
            if not user:
                raise HTTPException(500, "登录失败，请重试")
        else:
            db.refresh(user)
    else:
        # 老用户：同步企微最新姓名/部门（角色与状态绝不改动）
        changed = False
        if name and user.name != name:
            user.name = name
            changed = True
        if department and user.department != department:
            user.department = department
            changed = True
        if changed:
            db.commit()

    if getattr(user, "status", "active") != "active":
        raise HTTPException(403, "账号已停用，请联系管理员")

    token = issue_dev_token(user.id)
    db.add(AuditLog(user_id=user.id, action="login", resource="user",
                    detail={"mode": "wecom"}))
    db.commit()
    # 302 回首页，前端从 query 取 token 完成登录（避免 token 进浏览器历史的 # fragment 方案
    # 需要前端额外配合；query 方式与服务端 RedirectResponse 最简且可控，配合短 TTL 与 HTTPS 使用）
    return RedirectResponse(url=f"/?wecom_token={token}", status_code=302)
