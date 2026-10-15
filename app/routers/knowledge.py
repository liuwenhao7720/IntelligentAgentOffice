# -*- coding: utf-8 -*-
"""主动贡献知识库 API（工作台入口）。

三种贡献方式共用两个步骤：
1. 起草 —— 在线填写（前端直填）/ 上传文件（/knowledge/draft 带 attachment_ids）/
   自动总结（/knowledge/draft 带 text）；
2. 提交 —— POST /knowledge/contribute：写入简道云知识库表单
   （68ad15ab88c411d76390e0a2）+ 本地镜像即时可见 + 审计留痕。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import current_user
from ..database import User, get_db
from ..services import knowledge as kb
from ..services.jdy import jdy

router = APIRouter()


class KnowledgeDraftIn(BaseModel):
    """AI 起草请求：text（自动总结）与 attachment_ids（上传文件）可单独或同时给出。"""
    text: str = Field(default="", max_length=50000)
    attachment_ids: list[int] = Field(default_factory=list, max_length=5)
    model: str = Field(default="kimi", max_length=32)


class KnowledgeContributeIn(BaseModel):
    question: str = Field(min_length=1, max_length=250)
    answer: str = Field(min_length=1, max_length=8000)
    customer: str = Field(default="", max_length=120)
    project: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=60)
    remark: str = Field(default="", max_length=250)
    department: str = Field(default="", max_length=64)  # 空=取登录用户部门
    attachment_ids: list[int] = Field(default_factory=list, max_length=5)
    push_attachments: bool = True  # 是否把原文件上传到简道云附件控件


@router.get("/knowledge/fields")
def knowledge_fields(user: User = Depends(current_user)):
    """知识库表单字段定义 + 部门清单 + 连接状态（供前端渲染贡献表单）。"""
    dept_map = {} if jdy.mock else jdy.list_departments()
    return {
        "mode": "mock" if jdy.mock else "live",
        "entry_configured": bool(jdy.entry_id_knowledge),
        "fields": kb.KNOWLEDGE_FIELDS,
        "departments": sorted(dept_map.keys()),
        "default_department": user.department or "",
        "hint": "" if not jdy.mock else "JDY 为 MOCK 模式：提交将模拟写入，配置凭证后真实入简道云",
    }


@router.post("/knowledge/draft")
def knowledge_draft(body: KnowledgeDraftIn, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """AI 起草：自动总结（text）/ 上传文件（attachment_ids）→ 问答结构草稿。

    草稿仅返回前端预览编辑，不写库、不推简道云（确认提交走 /knowledge/contribute）。
    """
    if not body.text.strip() and not body.attachment_ids:
        raise HTTPException(422, "请粘贴素材文本，或先上传文件")
    draft: dict = {k: "" for k in ("question", "answer", "customer", "project", "country", "remark")}
    names: list[str] = []
    truncated = False
    if body.attachment_ids:
        d, names, truncated = kb.draft_from_attachments(db, user, body.attachment_ids, model=body.model)
        draft.update({k: v for k, v in d.items() if v})
    if body.text.strip():
        d = kb.draft_from_text(body.text, model=body.model)
        # 文本总结优先填充；文件草稿已填的字段若文本为空则保留文件结果
        for k, v in d.items():
            if v:
                draft[k] = v if k in ("question", "answer") or not draft.get(k) else draft[k]
    return {"draft": draft, "source_files": names, "truncated": truncated,
            "mock_llm": gateway_mock()}


def gateway_mock() -> bool:
    from ..services.model_gateway import gateway
    return bool(gateway._mock)  # noqa: SLF001 — 仅用于前端提示


@router.post("/knowledge/contribute")
def knowledge_contribute(body: KnowledgeContributeIn, db: Session = Depends(get_db),
                         user: User = Depends(current_user)):
    """确认提交：写入简道云知识库表单，成功后本地镜像立即可查。"""
    try:
        result = kb.contribute(
            db, user,
            fields=body.model_dump(exclude={"attachment_ids", "push_attachments"}),
            attachment_ids=body.attachment_ids,
            push_attachments=body.push_attachments,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not result["ok"]:
        raise HTTPException(502, f"写入简道云失败：{result.get('message') or '未知错误'}")
    return result
