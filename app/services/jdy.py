# -*- coding: utf-8 -*-
"""简道云（JianDaoYun）适配层。

两全其美原则：
- 企业微信 = 交互与沟通层（员工习惯的地方）
- 简道云 = 制度账本 / KPI 数据源（必须留痕的地方）
- 本适配器 = 桥：把结构化结果写入简道云，并回执到企微

生产：填写 JDY_APP_ID / JDY_API_KEY，走简道云开放接口。
开发：MOCK 模式，只落本地 push_log，便于联调与演示。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import httpx

from ..config import get_settings


@dataclass
class PushResult:
    ok: bool
    mode: str  # mock / live
    entry_id: str = ""
    message: str = ""
    raw: dict = field(default_factory=dict)


class JDYClient:
    """简道云数据接口客户端（表单/流程）。"""

    def __init__(self) -> None:
        s = get_settings()
        self.app_id = getattr(s, "jdy_app_id", "") or ""
        self.api_key = getattr(s, "jdy_api_key", "") or ""
        self.entry_id_task = getattr(s, "jdy_entry_task", "") or ""       # 任务管理表单
        self.entry_id_knowledge = getattr(s, "jdy_entry_knowledge", "") or ""  # 知识库
        self.base = getattr(s, "jdy_base_url", "") or "https://api.jiandaoyun.com/api/v1"
        self.mock = not (self.app_id and self.api_key)

    def push_form(self, entry_id: str, data: dict, note: str = "") -> PushResult:
        """写入一条简道云表单数据。"""
        if self.mock or not entry_id:
            return PushResult(
                ok=True,
                mode="mock",
                entry_id=f"MOCK-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                message=f"[MOCK] 已模拟写入简道云 entry={entry_id or 'default'} {note}",
                raw={"data": data},
            )
        url = f"{self.base}/app/{self.app_id}/entry/{entry_id}/data"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"data": data},
                )
                resp.raise_for_status()
                obj = resp.json()
            return PushResult(ok=True, mode="live", entry_id=str(obj.get("_id", "")), raw=obj)
        except Exception as e:  # noqa: BLE001
            return PushResult(ok=False, mode="live", message=str(e))

    def push_task(self, data: dict, note: str = "") -> PushResult:
        return self.push_form(self.entry_id_task, data, note=note or "任务")

    def push_knowledge(self, data: dict, note: str = "") -> PushResult:
        return self.push_form(self.entry_id_knowledge, data, note=note or "知识库")


jdy = JDYClient()


# ---------------------------------------------------------------------------
# 简道云任务五要素模板（对齐 KPI 数据采集字段）
# ---------------------------------------------------------------------------
def build_jdy_task(
    title: str,
    start: str,
    due: str,
    owner: str,
    priority: str = "较高",
    project: str = "",
    category: str = "日常工作",
    description: str = "",
    attachments: Optional[list] = None,
    collaborators: Optional[list] = None,
    extra: Optional[dict] = None,
) -> dict:
    """构造简道云「任务管理」字段（字段名以实际表单为准，可配置映射）。"""
    payload = {
        "任务名称": title,
        "开始时间": start,
        "截止时间": due,
        "负责人": [owner] if isinstance(owner, str) else owner,
        "优先级": priority,
        "所属项目": project,
        "任务一级分类": category,
        "任务描述": description,
        "协作人": collaborators or [],
        "添加附件": attachments or [],
    }
    if extra:
        payload.update(extra)
    return payload


def build_jdy_knowledge(title: str, content: str, tags: list | None = None, dept: str = "") -> dict:
    return {
        "文档标题": title,
        "文档内容": content,
        "标签": tags or [],
        "所属部门": dept,
        "提交时间": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }
