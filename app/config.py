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
    mimo_base_url: str = field(default_factory=lambda: _env("MIMO_BASE_URL", "https://api.mimo.com/v1"))
    mimo_model: str = field(default_factory=lambda: _env("MIMO_MODEL", "mimo-v2.6"))

    deepseek_api_key: str = field(default_factory=lambda: _env("DEEPSEEK_API_KEY"))
    deepseek_base_url: str = field(default_factory=lambda: _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
    deepseek_model: str = field(default_factory=lambda: _env("DEEPSEEK_MODEL", "deepseek-chat"))

    kimi_api_key: str = field(default_factory=lambda: _env("KIMI_API_KEY"))
    kimi_base_url: str = field(default_factory=lambda: _env("KIMI_BASE_URL", "https://api.moonshot.cn/v1"))
    kimi_model: str = field(default_factory=lambda: _env("KIMI_MODEL", "moonshot-v1-128k"))

    # 无密钥时自动进入 mock 模式，便于本地验收
    mock_llm: bool = field(default_factory=lambda: _env("MOCK_LLM", "auto") == "1")

    # 企业微信（生产启用；开发可用 dev 登录）
    wecom_corp_id: str = field(default_factory=lambda: _env("WECOM_CORP_ID"))
    wecom_agent_id: str = field(default_factory=lambda: _env("WECOM_AGENT_ID"))
    wecom_secret: str = field(default_factory=lambda: _env("WECOM_SECRET"))
    enable_dev_login: bool = field(default_factory=lambda: _env("ENABLE_DEV_LOGIN", "1") == "1")

    request_timeout: int = int(_env("REQUEST_TIMEOUT", "120") or "120")

    # 简道云（JianDaoYun）开放接口
    jdy_app_id: str = field(default_factory=lambda: _env("JDY_APP_ID"))
    jdy_api_key: str = field(default_factory=lambda: _env("JDY_API_KEY"))
    jdy_base_url: str = field(default_factory=lambda: _env("JDY_BASE_URL", "https://api.jiandaoyun.com/api/v1"))
    jdy_entry_task: str = field(default_factory=lambda: _env("JDY_ENTRY_TASK"))
    jdy_entry_knowledge: str = field(default_factory=lambda: _env("JDY_ENTRY_KNOWLEDGE"))

    def any_model_key(self) -> bool:
        return bool(self.mimo_api_key or self.deepseek_api_key or self.kimi_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
