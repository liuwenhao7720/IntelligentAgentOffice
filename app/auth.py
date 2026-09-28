# -*- coding: utf-8 -*-
"""T03 鉴权：开发态简易登录 + 预留企业微信 OAuth。"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import get_settings
from .database import User, get_db

# 开发态内存 token（生产替换为 JWT + 企微 OAuth）
_DEV_TOKENS: dict[str, int] = {}
_TOKEN_SEQ = 1


def issue_dev_token(user_id: int) -> str:
    global _TOKEN_SEQ
    token = f"dev-token-{_TOKEN_SEQ}"
    _TOKEN_SEQ += 1
    _DEV_TOKENS[token] = user_id
    return token


def current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少访问令牌")
    token = authorization.removeprefix("Bearer ").strip()
    uid = _DEV_TOKENS.get(token)
    if uid is None:
        # 预留：此处校验 JWT / 企微 OAuth 令牌
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


def dev_login_enabled() -> bool:
    return get_settings().enable_dev_login
