# -*- coding: utf-8 -*-
"""T03 鉴权：开发态简易登录 + 预留企业微信 OAuth。

令牌设计（v2，支持多 worker / 多用户并发、服务重启不丢会话）：
- 无状态 HMAC-SHA256 签名令牌，格式：vflo1.<payload_b64>.<sig_b64>
- payload 内含 uid / iat / exp / nonce，任意 worker 进程均可独立校验，
  不再依赖进程内存字典（旧实现导致多 worker 下令牌随机 401 / 串号）
- 令牌由 SECRET_KEY 签名，不可伪造、不可预测，杜绝跨用户串号与令牌猜测
- 自带过期时间（TOKEN_TTL_HOURS，默认 168 小时 = 7 天）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import get_settings
from .database import User, get_db

_TOKEN_PREFIX = "vflo1"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign(payload_b64: str) -> str:
    key = get_settings().secret_key.encode("utf-8")
    return _b64e(hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).digest())


def issue_dev_token(user_id: int) -> str:
    """签发无状态签名令牌（保留旧函数名以兼容调用方）。

    每次签发带随机 nonce，同一用户多次登录获得的令牌互不相同的，
    但全部可并行有效（支持同一账号多端同时在线）。
    """
    ttl = max(1, get_settings().token_ttl_hours) * 3600
    now = int(time.time())
    payload = {
        "uid": user_id,
        "iat": now,
        "exp": now + ttl,
        "nonce": secrets.token_hex(8),
    }
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{_TOKEN_PREFIX}.{payload_b64}.{_sign(payload_b64)}"


def parse_token(token: str) -> "int | None":
    """校验令牌并返回 user_id；格式错误 / 签名不符 / 已过期返回 None。"""
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
        return None
    payload_b64, sig = parts[1], parts[2]
    # 常数时间比较，防时序侧信道
    if not hmac.compare_digest(sig, _sign(payload_b64)):
        return None
    try:
        payload = json.loads(_b64d(payload_b64))
    except (ValueError, UnicodeDecodeError):
        return None
    uid = payload.get("uid")
    exp = payload.get("exp", 0)
    if not isinstance(uid, int) or isinstance(uid, bool):
        return None
    if not isinstance(exp, (int, float)) or exp < time.time():
        return None
    return uid


def current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少访问令牌")
    token = authorization.removeprefix("Bearer ").strip()
    uid = parse_token(token)
    if uid is None:
        # 预留：此处可叠加校验 JWT / 企微 OAuth 令牌
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    # 登录隔离：停用账号立即失效（token 无状态但每请求查库，无需吊销表）
    if getattr(user, "status", "active") != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号已停用，请联系管理员")
    return user


# ---------- 角色权限（RBAC） ----------
# 四角色（用户确认的口径）：staff 员工 / manager 部门经理 / compliance 合规官 / admin 管理员。
# 权限点集中定义于此，路由统一用 require_perm("...") 校验，避免散落硬编码 role 判断。
ROLES = ("staff", "manager", "compliance", "admin")

ROLE_PERMS: dict[str, set[str]] = {
    "staff": set(),
    # 部门经理：查看本部门早宣/晚总推送统计与未推送名单（附件5 §8.5）+ 手动触发简道云同步
    "manager": {"briefing.stats.dept", "jdy.sync"},
    # 合规官：出口管制审查单终审（附件1 §2.4/G5、WBS T20）+ 合规规则/资料资产维护
    "compliance": {"export.review", "compliance.rules"},
    # 管理员：全部权限（* 通配）
    "admin": {"*"},
}


def has_perm(user: User, perm: str) -> bool:
    perms = ROLE_PERMS.get(user.role or "staff", set())
    return "*" in perms or perm in perms


def require_perm(perm: str):
    """权限点依赖工厂：用法 user: User = Depends(require_perm("export.review"))。"""
    def _dep(user: User = Depends(current_user)) -> User:
        if not has_perm(user, perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "没有该操作的权限")
        return user
    return _dep


def require_admin(user: User = Depends(current_user)) -> User:
    if not has_perm(user, "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


def dev_login_enabled() -> bool:
    return get_settings().enable_dev_login
