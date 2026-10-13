# -*- coding: utf-8 -*-
"""T01 项目配置：环境变量驱动，一主两备模型。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


@dataclass
class Settings:
    app_name: str = "V-FLO 极简智能办公系统"
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "dev-secret-change-me"))
    # 生产（单服务器 Docker Compose）使用 PostgreSQL：
    #   postgresql+psycopg2://vflo:password@db:5432/vflo_office
    # 开发默认 SQLite，便于本地冒烟；生产由 .env / compose 注入 DATABASE_URL
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./vflo_office.db"))
    # 连接池（生产按单机 32C/256GB 建议值，可经环境变量覆盖）
    db_pool_size: int = int(_env("DB_POOL_SIZE", "10") or "10")
    db_max_overflow: int = int(_env("DB_MAX_OVERFLOW", "20") or "20")
    db_pool_recycle: int = int(_env("DB_POOL_RECYCLE", "1800") or "1800")

    # 三款大模型（OpenAI 兼容接口）
    mimo_api_key: str = field(default_factory=lambda: _env("MIMO_API_KEY"))
    mimo_base_url: str = field(default_factory=lambda: _env("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"))
    mimo_model: str = field(default_factory=lambda: _env("MIMO_MODEL", "mimo-v2.6"))

    deepseek_api_key: str = field(default_factory=lambda: _env("DEEPSEEK_API_KEY"))
    deepseek_base_url: str = field(default_factory=lambda: _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
    deepseek_model: str = field(default_factory=lambda: _env("DEEPSEEK_MODEL", "deepseek-chat"))

    kimi_api_key: str = field(default_factory=lambda: _env("KIMI_API_KEY"))
    kimi_base_url: str = field(default_factory=lambda: _env("KIMI_BASE_URL", "https://api.moonshot.cn/v1"))
    kimi_model: str = field(default_factory=lambda: _env("KIMI_MODEL", "moonshot-v1-128k"))

    minimax_api_key: str = field(default_factory=lambda: _env("MINIMAX_API_KEY"))
    minimax_base_url: str = field(default_factory=lambda: _env("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"))
    minimax_model: str = field(default_factory=lambda: _env("MINIMAX_MODEL", "MiniMax-M3"))

    # 无密钥时自动进入 mock 模式，便于本地验收
    # 取值：1/true/yes/on（不区分大小写）强制 mock；其余（如 auto）= 无任何模型 Key 时自动 mock
    mock_llm: bool = field(default_factory=lambda: _env("MOCK_LLM", "auto").lower() in ("1", "true", "yes", "on"))

    # 企业微信（生产启用；开发可用 dev 登录）
    wecom_corp_id: str = field(default_factory=lambda: _env("WECOM_CORP_ID"))
    wecom_agent_id: str = field(default_factory=lambda: _env("WECOM_AGENT_ID"))
    wecom_secret: str = field(default_factory=lambda: _env("WECOM_SECRET"))
    # 企业微信智能机器人（SDK 长连接）凭证
    wecom_bot_id: str = field(default_factory=lambda: _env("WECOM_BOT_ID"))
    wecom_bot_secret: str = field(default_factory=lambda: _env("WECOM_BOT_SECRET"))
    # 企微扫码登录（qrConnect）：0=关闭；默认 1=凭证齐备即启用（未配置凭证时前端自动隐藏入口）
    wecom_login_enabled: bool = field(default_factory=lambda: _env("WECOM_LOGIN_ENABLED", "1") != "0")
    # 扫码后浏览器回调地址（企微管理后台需登记该域名/地址为可信回调；生产改为内网入口 https://host:8008/api/v1/auth/wecom/callback）
    wecom_redirect_uri: str = field(
        default_factory=lambda: _env("WECOM_REDIRECT_URI", "http://127.0.0.1:8000/api/v1/auth/wecom/callback"))
    enable_dev_login: bool = field(default_factory=lambda: _env("ENABLE_DEV_LOGIN", "1") == "1")
    # 登录令牌有效期（小时），默认 7 天；令牌为 HMAC 无状态签名，重启/多 worker 不失效
    token_ttl_hours: int = int(_env("TOKEN_TTL_HOURS", "168") or "168")
    # 开发登录管理员白名单（逗号分隔的姓名或 dev_姓名_部门）；不在名单内的一律 staff，防越权
    dev_admin_users: str = field(default_factory=lambda: _env("DEV_ADMIN_USERS"))

    request_timeout: int = int(_env("REQUEST_TIMEOUT", "120") or "120")

    # 个别模型对 temperature 有硬性限制（如 kimi k3 仅允许 1），配置后对该供应商强制覆盖
    kimi_temperature: str = field(default_factory=lambda: _env("KIMI_TEMPERATURE"))

    # 简道云（JianDaoYun）开放接口
    jdy_app_id: str = field(default_factory=lambda: _env("JDY_APP_ID"))
    jdy_api_key: str = field(default_factory=lambda: _env("JDY_API_KEY"))
    jdy_base_url: str = field(default_factory=lambda: _env("JDY_BASE_URL", "https://api.jiandaoyun.com/api/v1"))
    jdy_entry_task: str = field(default_factory=lambda: _env("JDY_ENTRY_TASK"))
    jdy_entry_knowledge: str = field(default_factory=lambda: _env("JDY_ENTRY_KNOWLEDGE"))
    # 简道云 → 本地镜像单向拉取（仿 v-crm：独立 poller 进程 + 本地镜像表）
    jdy_auto_sync_enabled: bool = field(default_factory=lambda: _env("JDY_AUTO_SYNC_ENABLED", "1") != "0")
    jdy_sync_interval_seconds: int = int(_env("JDY_SYNC_INTERVAL_SECONDS", "3600") or "3600")
    jdy_sync_max_pages: int = int(_env("JDY_SYNC_MAX_PAGES", "200") or "200")  # 单表单上限 200×100=20000 行

    # 制裁名单 API（附件1 WBS T19：屏蔽源可插拔；未配置时用本地关键词库）
    sanctions_api_url: str = field(default_factory=lambda: _env("SANCTIONS_API_URL"))
    sanctions_api_key: str = field(default_factory=lambda: _env("SANCTIONS_API_KEY"))

    # CORS 白名单（附件4 技术基线·安全；逗号分隔，默认仅同源不放开）
    cors_origins: str = field(default_factory=lambda: _env("CORS_ORIGINS"))

    # 个人月度 token 额度（附件3 §2.3：超额仅提醒不锁死；0=不限）
    monthly_token_quota: int = int(_env("MONTHLY_TOKEN_QUOTA", "0") or "0")

    # ===== 智能对话模块（类 DeepSeek Harness：文件上传 + 多轮对话）=====
    # 上传文件存储目录（开发默认 ./data/uploads；生产 compose 注入 /app/uploads）
    upload_dir: str = field(default_factory=lambda: _env("UPLOAD_DIR", "./data/uploads"))
    # 单文件大小上限（MB）
    upload_max_mb: int = int(_env("UPLOAD_MAX_MB", "10") or "10")
    # 单消息最多携带附件数
    chat_max_attachments: int = int(_env("CHAT_MAX_ATTACHMENTS", "5") or "5")
    # 发送消息时携带的历史轮数（user+assistant 计一轮）
    chat_history_turns: int = int(_env("CHAT_HISTORY_TURNS", "12") or "12")
    # 附件文本注入上限：单文件 / 单消息全部附件合计（字符）
    chat_file_max_chars: int = int(_env("CHAT_FILE_MAX_CHARS", "8000") or "8000")
    chat_files_max_chars: int = int(_env("CHAT_FILES_MAX_CHARS", "24000") or "24000")

    def any_model_key(self) -> bool:
        return bool(self.mimo_api_key or self.deepseek_api_key or self.kimi_api_key or self.minimax_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
