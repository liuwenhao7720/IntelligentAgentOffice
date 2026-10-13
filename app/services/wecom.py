# -*- coding: utf-8 -*-
"""企业微信扫码登录（OAuth2 / qrConnect）客户端。

流程（官方「扫码授权登录」）：
  1. 前端整页跳转到 build_qr_connect_url(state) 生成的授权页（open.work.weixin.qq.com）
  2. 用户用企业微信 App 扫码并确认 → 浏览器重定向回 redirect_uri?code=...&state=...
  3. 服务端 GET /auth/wecom/callback：验 state → get_user_id(code) → get_user_detail(userid)
     → 按 wecom_userid 建号/复用 → 签发本系统 token → 302 回首页（query 带 token）

网络兜底：所有对企微 API 的调用都收敛为 WeComError；内网出网受限时路由层降级为
友好 503，开发登录继续可用。单元测试通过 monkeypatch 替换 _get 完成，无需真实网络。
"""
from __future__ import annotations

import time
from urllib.parse import quote

import httpx

from ..config import get_settings

API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
QR_CONNECT = "https://open.work.weixin.qq.com/wwopen/sso/qrConnect"


class WeComError(Exception):
    """企微 API 调用失败（网络/凭证/业务错误码统一收敛）。"""


def is_wecom_configured() -> bool:
    s = get_settings()
    return bool(s.wecom_login_enabled and s.wecom_corp_id and s.wecom_agent_id and s.wecom_secret)


class WeComClient:
    """企微服务端 API（同步 httpx；token 进程内缓存，提前 5 分钟过期）。"""

    def __init__(self) -> None:
        self._token: str = ""
        self._token_exp: float = 0.0

    def _get(self, url: str, params: dict) -> dict:
        try:
            with httpx.Client(timeout=8) as client:
                resp = client.get(url, params=params)
            obj = resp.json()
        except Exception as e:  # noqa: BLE001 — 网络/JSON 异常统一收敛
            raise WeComError(f"企微接口不可达：{type(e).__name__}") from e
        if obj.get("errcode"):
            raise WeComError(f"企微接口报错 {obj.get('errcode')}: {obj.get('errmsg', '')}")
        return obj

    def get_corp_token(self) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        s = get_settings()
        obj = self._get(f"{API_BASE}/gettoken", {
            "corpid": s.wecom_corp_id, "corpsecret": s.wecom_secret,
        })
        token = obj.get("access_token")
        if not token:
            raise WeComError("gettoken 未返回 access_token")
        self._token = token
        self._token_exp = time.time() + int(obj.get("expires_in", 7200)) - 300
        return token

    def get_user_id(self, code: str) -> str:
        """扫码回调 code → 企业成员 userid。非成员/已过期 code 抛 WeComError。"""
        obj = self._get(f"{API_BASE}/auth/getuserinfo", {
            "access_token": self.get_corp_token(), "code": code,
        })
        userid = obj.get("userid") or obj.get("UserId") or ""
        if not userid:
            # errcode=0 但无 userid：扫码者为非企业成员（仅有 openid）
            raise WeComError("扫码者不是企业成员，无法登录")
        return userid

    def get_user_detail(self, userid: str) -> dict:
        """userid → {name, department_names}；详情失败时降级为 userid 占位。"""
        try:
            obj = self._get(f"{API_BASE}/user/get", {
                "access_token": self.get_corp_token(), "userid": userid,
            })
        except WeComError:
            return {"name": userid, "department_names": ""}
        name = obj.get("name") or userid
        # department 为部门 id 列表；名称需再调 department/get，降级策略：留空由管理员维护
        dept_ids = obj.get("department") or []
        dept_names = ""
        if dept_ids:
            try:
                dobj = self._get(f"{API_BASE}/department/get", {
                    "access_token": self.get_corp_token(), "id": dept_ids[0],
                })
                dept_names = ((dobj.get("department") or {}).get("name") or "")
            except WeComError:
                dept_names = ""
        return {"name": name, "department_names": dept_names}


def build_qr_connect_url(state: str) -> str:
    s = get_settings()
    redirect = quote(s.wecom_redirect_uri, safe="")
    return (
        f"{QR_CONNECT}?appid={s.wecom_corp_id}&agentid={s.wecom_agent_id}"
        f"&redirect_uri={redirect}&state={quote(state, safe='')}"
    )
