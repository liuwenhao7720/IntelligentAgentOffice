# -*- coding: utf-8 -*-
"""主动贡献知识库：上传文件 / 在线填写 / 自动总结 → 简道云知识库表单。

目标表单：简道云知识库 entry_id=68ad15ab88c411d76390e0a2（字段已实测核对）：
    客户(text) / 项目(text) / 问题(text) / 回答(textarea)
    附件(upload) / 备注(text) / 国家(text) / 部门(dept，仅接受 dept_no 数字)

数据流（写）：本模块 → JDYClient.push_knowledge → 简道云；成功后立即 upsert
本地镜像 jdy_records（kind=knowledge），前端无需等 poller 即可展示与搜索。
数据流（读）：jdy_poller 周期全量拉取（jdy_sync），本模块的即时镜像与其同构。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import AuditLog, ChatAttachment, JdyRecord, User
from ..services.jdy import (
    KNOWLEDGE_LABEL_TO_WIDGET, build_jdy_knowledge, jdy, to_widget_payload,
)
from ..services.jdy_sync import _clamp_proj, _project_generic
from ..services.model_gateway import gateway

logger = logging.getLogger("vflo.knowledge")

# 知识库表单字段定义（供前端渲染「在线填写」表单；顺序即表单顺序）
KNOWLEDGE_FIELDS: list[dict] = [
    {"key": "question", "label": "问题", "required": True, "multiline": False,
     "ph": "客户提出的问题 / 知识点标题，如：机械密封金属面备件是否必须提供"},
    {"key": "answer", "label": "回答", "required": True, "multiline": True,
     "ph": "标准答案 / 经验做法：结论先行，含依据、适用范围与注意事项"},
    {"key": "customer", "label": "客户", "required": False, "multiline": False,
     "ph": "如 MTO / Enter Engineering Pte. Ltd"},
    {"key": "project", "label": "项目", "required": False, "multiline": False,
     "ph": "项目编号或名称，如 S1240058"},
    {"key": "country", "label": "国家", "required": False, "multiline": False,
     "ph": "如 乌兹别克斯坦(Uzbekistan)"},
    {"key": "remark", "label": "备注", "required": False, "multiline": False,
     "ph": "来源/适用范围等补充说明（选填）"},
]

_DRAFT_KEYS = ("question", "answer", "customer", "project", "country", "remark")

# 部门名 → dept_no 的进程内缓存（通讯录极少变动，5 分钟 TTL）
_DEPT_CACHE: dict = {"at": 0.0, "map": {}}
_DEPT_CACHE_TTL = 300

# 素材注入 LLM 的长度上限（自动总结/文件提取共用）
_MATERIAL_MAX_CHARS = 12000


def resolve_dept_no(name: str) -> int | None:
    """部门名 → 简道云 dept_no（带缓存；精确匹配失败时尝试去空格/全半角后匹配）。"""
    name = (name or "").strip()
    if not name or jdy.mock:
        return None
    now = time.monotonic()
    if now - _DEPT_CACHE["at"] > _DEPT_CACHE_TTL:
        _DEPT_CACHE["map"] = jdy.list_departments()
        _DEPT_CACHE["at"] = now
    dept_map = _DEPT_CACHE["map"]
    if name in dept_map:
        return dept_map[name]
    squashed = name.replace(" ", "").replace("（", "(").replace("）", ")")
    for k, v in dept_map.items():
        if k.replace(" ", "").replace("（", "(").replace("）", ")") == squashed:
            return v
    return None


# ---------------------------------------------------------------------------
# AI 草稿提取（自动总结 / 上传文件共用）
# ---------------------------------------------------------------------------
def _rule_based_draft(text: str) -> dict:
    """LLM 不可用/输出非 JSON 时的兜底提取：首行当问题，全文当回答。"""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    question = ""
    for ln in lines[:5]:
        ln = re.sub(r"^[#>*\-\d.、\s]+", "", ln)
        if len(ln) >= 6:
            question = ln[:120]
            break
    if not question:
        question = (lines[0][:120] if lines else "（待补充问题）")
    return {"question": question, "answer": (text or "").strip()[:2000],
            "customer": "", "project": "", "country": "", "remark": ""}


def _is_placeholder(v: str) -> bool:
    """LLM 把提示词中的 JSON 示例原样回显时的占位值识别（如 "..."）。"""
    return not v or set(v) <= {".", "…", " ", "。","，", ","}


def draft_from_text(text: str, model: str = "kimi") -> dict:
    """把一段素材（粘贴文本/文件解析文本）AI 总结为知识库问答结构草稿。

    输出键固定为 _DRAFT_KEYS；mock 模式直接走规则提取，
    LLM 失败/非 JSON/占位回显时同样回退规则提取（不阻断）。
    """
    text = (text or "").strip()
    if not text:
        return {k: "" for k in _DRAFT_KEYS}
    material = text[:_MATERIAL_MAX_CHARS]
    if getattr(gateway, "_mock", False):  # mock 模式：无真实模型，直接规则提取
        return _rule_based_draft(text)
    prompt = (
        "你是企业知识库整理专家。把下面的原始素材提炼成一条知识库问答记录，输出 JSON 对象：\n"
        '{"question": "...", "answer": "...", "customer": "...", "project": "...", '
        '"country": "...", "remark": "..."}\n'
        "要求：\n"
        "1. question=客户/业务方提出的核心问题或知识点标题，一句话，不超过 60 字；\n"
        "2. answer=标准答案/经验做法，结论先行、分条陈述，保留关键数据与依据，不超过 800 字；\n"
        "3. customer/project/country 从素材中识别（客户名、项目编号或名称、国家），素材没有就留空字符串，不要编造；\n"
        "4. remark 填素材来源说明（如文件名、场景），没有就留空；\n"
        "5. 只输出 JSON 对象，不要解释，不要用 markdown 代码块。\n\n"
        f"原始素材：\n{material}"
    )
    draft: dict = {}
    try:
        result = gateway.chat(
            [{"role": "system", "content": "只输出 JSON 对象，不要解释，不要用 markdown 代码块。"},
             {"role": "user", "content": prompt}],
            model=model or "kimi",
            temperature=0.2,
            max_tokens=1200,
        )
        m = re.search(r"\{.*\}", result.text or "", re.S)
        if m:
            raw = json.loads(m.group(0))
            draft = {k: str(raw.get(k) or "").strip() for k in _DRAFT_KEYS}
            draft = {k: ("" if _is_placeholder(v) else v) for k, v in draft.items()}
    except Exception as e:  # noqa: BLE001 — AI 提取失败回退规则提取
        logger.info("knowledge draft llm fallback: %s", type(e).__name__)
        draft = {}
    if not draft.get("question") or not draft.get("answer"):
        fallback = _rule_based_draft(text)
        # 已识别出的字段保留（如 customer/project），主体缺失才用兜底补
        for k in _DRAFT_KEYS:
            if not draft.get(k):
                draft[k] = fallback.get(k, "")
    draft["answer"] = draft["answer"][:8000]
    draft["question"] = draft["question"][:250]
    return draft


def draft_from_attachments(db: Session, user: User, attachment_ids: list[int],
                           model: str = "kimi") -> tuple[dict, list[str], bool]:
    """上传文件方式：读取已上传附件的解析文本 → AI 提取草稿。

    返回 (draft, 使用的文件名列表, 是否被截断)。
    """
    names: list[str] = []
    chunks: list[str] = []
    total = 0
    truncated = False
    for aid in attachment_ids[:5]:
        att = db.get(ChatAttachment, int(aid))
        if not att or (att.user_id != user.id and user.role != "admin"):
            continue
        text = (att.extracted_text or "").strip()
        if not text:
            continue
        names.append(att.filename)
        room = _MATERIAL_MAX_CHARS - total
        if room <= 0:
            truncated = True
            break
        if len(text) > room:
            text = text[:room]
            truncated = True
        chunks.append(f"【文件《{att.filename}》内容】\n{text}")
        total += len(text)
    draft = draft_from_text("\n\n".join(chunks), model=model) if chunks else {k: "" for k in _DRAFT_KEYS}
    if names and not draft.get("remark"):
        draft["remark"] = "来源文件：" + "、".join(names)
    return draft, names, truncated


# ---------------------------------------------------------------------------
# 贡献提交：推送简道云 + 本地镜像即时可见 + 审计
# ---------------------------------------------------------------------------
def _widget_values(payload: dict) -> dict:
    """to_widget_payload 结果 {widget: {value}} → {widget: 值}（镜像/展示用）。"""
    return {w: (v.get("value") if isinstance(v, dict) else v) for w, v in payload.items()}


def upsert_knowledge_mirror(db: Session, data_id: str, widget_payload: dict,
                            contributor: str = "", dept_name: str = "") -> None:
    """推送成功后把记录写入本地镜像（与 jdy_sync 全量拉取结果同构）。

    raw._fields 用 {widget: 值} + 系统字段（creator/createTime），
    raw._labels 用静态标签映射；投影走 _project_generic（标题取「问题」字段）。
    部门控件本地存 {name, dept_no} 结构（与简道云端返回一致，投影显示部门名）。
    """
    labels: dict[str, str] = {w: lbl for lbl, w in KNOWLEDGE_LABEL_TO_WIDGET.items()}
    labels.update({"creator": "创建人", "createTime": "创建时间", "updateTime": "更新时间"})
    fields = _widget_values(widget_payload)
    dept_widget = KNOWLEDGE_LABEL_TO_WIDGET["部门"]
    if dept_name and isinstance(fields.get(dept_widget), (int, float)):
        fields[dept_widget] = {"name": dept_name, "dept_no": int(fields[dept_widget])}
    fields["creator"] = {"name": contributor} if contributor else ""
    fields["createTime"] = datetime.utcnow().isoformat() + "Z"
    proj = _clamp_proj(_project_generic(fields, labels))
    if not proj["title"]:
        proj["title"] = f"（无标题记录 {data_id[-6:]}）"
    raw = {"_fields": fields, "_labels": labels}
    rec = db.execute(
        select(JdyRecord).where(JdyRecord.entry_id == jdy.entry_id_knowledge,
                                JdyRecord.data_id == data_id)
    ).scalar_one_or_none()
    if rec:
        for k, v in proj.items():
            setattr(rec, k, v)
        rec.raw = raw
        rec.synced_at = datetime.utcnow()
    else:
        db.add(JdyRecord(entry_id=jdy.entry_id_knowledge, data_id=data_id,
                         kind="knowledge", raw=raw, **proj))


def contribute(db: Session, user: User, fields: dict,
               attachment_ids: list[int] | None = None,
               push_attachments: bool = True) -> dict:
    """确认提交：构造 payload → 推送简道云 → 本地镜像 upsert → 审计留痕。

    fields: {question*, answer*, customer, project, country, remark, department}
    - 部门：默认取登录用户部门；能解析为 dept_no 才写入部门控件，
      否则名称并入备注（dept 控件传名称会被简道云拒绝）；
    - 附件：attachment_ids 指向本系统已上传文件（chat/uploads），
      push_attachments=True 时逐个上传到简道云换 fileToken；
      APIKey 无文件权限（403）等失败时降级为把文件名写入备注。
    """
    question = (fields.get("question") or "").strip()
    answer = (fields.get("answer") or "").strip()
    if not question or not answer:
        raise ValueError("「问题」与「回答」为必填项")
    if not jdy.entry_id_knowledge:
        raise ValueError("未配置知识库表单（JDY_ENTRY_KNOWLEDGE）")

    remark = (fields.get("remark") or "").strip()
    dept_name = (fields.get("department") or user.department or "").strip()
    dept_no = resolve_dept_no(dept_name)
    if dept_name and dept_no is None and not jdy.mock:
        remark = (remark + "；" if remark else "") + f"部门：{dept_name}"

    # 附件上传（降级：失败文件名并入备注）
    attach_tokens: list[dict] = []
    failed_files: list[str] = []
    if push_attachments and attachment_ids:
        for aid in attachment_ids[:5]:
            att = db.get(ChatAttachment, int(aid))
            if not att or (att.user_id != user.id and user.role != "admin"):
                continue
            try:
                content = Path(att.storage_path).read_bytes()
            except OSError:
                failed_files.append(att.filename)
                continue
            r = jdy.upload_file(jdy.entry_id_knowledge, att.filename, content, att.mime or "")
            if r.ok and r.entry_id:
                attach_tokens.append({"fileToken": r.entry_id, "name": att.filename})
            else:
                failed_files.append(att.filename)
                logger.info("knowledge attach upload failed: %s (%s)", att.filename, r.message)
    if failed_files:
        remark = (remark + "；" if remark else "") + \
                 "附件暂存本系统（简道云附件上传未开通）：" + "、".join(failed_files)

    payload = build_jdy_knowledge(
        question=question[:250],
        answer=answer[:8000],
        customer=(fields.get("customer") or "").strip()[:120],
        project=(fields.get("project") or "").strip()[:120],
        country=(fields.get("country") or "").strip()[:60],
        remark=remark[:250],
        dept=dept_no if dept_no is not None else "",
        attachments=attach_tokens,
    )
    result = jdy.push_knowledge(payload, note="主动贡献知识库")
    widget_payload = to_widget_payload(payload)
    out = {
        "ok": result.ok,
        "mode": result.mode,
        "data_id": result.entry_id if result.ok else "",
        "message": result.message,
        "dept_written": dept_no is not None,
        "attachments_pushed": len(attach_tokens),
        "attachments_failed": failed_files,
        "mirrored": False,
    }
    if result.ok and result.entry_id and not result.entry_id.startswith("MOCK-"):
        try:
            upsert_knowledge_mirror(db, result.entry_id, widget_payload,
                                    contributor=user.name, dept_name=dept_name)
            db.commit()
            out["mirrored"] = True
        except Exception as e:  # noqa: BLE001 — 镜像失败不阻断（poller 会兜底拉取）
            db.rollback()
            logger.warning("knowledge mirror upsert failed: %s", e)
            out["mirror_error"] = str(e)
    db.add(AuditLog(user_id=user.id, action="knowledge.contribute", resource="jdy:knowledge",
                    detail={"mode": result.mode, "ok": result.ok, "data_id": out["data_id"],
                            "question": question[:80], "dept": dept_name,
                            "attachments": len(attach_tokens)}))
    db.commit()
    return out
