# -*- coding: utf-8 -*-
"""简道云 → 本地镜像同步编排（单向拉取；v-crm 镜像模式的本项目实现）。

语义：
- 全量拉取已配置表单（任务管理/知识库）→ 逐行 upsert 到 jdy_records；
- 全镜像 prune：本次未见的数据视为简道云侧已删除，本地同步删除；
  但若拉取被 max_pages 截断则跳过 prune（防因半截数据误删镜像）；
- 每轮写 JdySyncLog；mock/未配置凭证 → skipped 日志，不报错；
- 错误隔离：单表单失败不影响其他表单（run_full_sync 内捕获）。
"""
from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import AuditLog, JdyRecord, JdySyncLog
from ..services.jdy import jdy
from ..services.task_agent import JDY_FIELD_MAP, _jdy_scalar, jdy_row_to_task

# kind → 中文名（前端展示/日志用）
KIND_LABELS = {"task": "任务管理", "knowledge": "知识库"}

# 投影列长度钳制（防个别行的数组型字段 join 后超列宽导致整批 INSERT 失败）
_PROJ_WIDTHS = {"title": 250, "status": 30, "owner": 120, "dept": 60,
                "due_time": 32, "submit_time": 32}


def _clamp_proj(proj: dict) -> dict:
    return {k: (v[: _PROJ_WIDTHS.get(k, 256)] if isinstance(v, str) else v)
            for k, v in proj.items()}


def configured_entries() -> dict[str, str]:
    """已配置 entry 的 {kind: entry_id}（未配置的不参与同步）。"""
    out = {"task": jdy.entry_id_task, "knowledge": jdy.entry_id_knowledge}
    return {k: v for k, v in out.items() if v}


def _project_task(fields: dict) -> dict:
    """任务管理行 → 投影列（复用 task_agent 的字段映射，widget 已对照字段汇总表）。"""
    t = jdy_row_to_task(fields)
    dept = _jdy_scalar(fields.get(JDY_FIELD_MAP.get("dept", "")))
    return {
        "title": t.get("title", ""),
        "status": t.get("status", ""),
        "owner": t.get("owner", ""),
        "dept": str(dept or ""),
        "due_time": t.get("due_time", "")[:32],
        "submit_time": t.get("start_time", "")[:32],
    }


def _project_generic(fields: dict, labels: dict[str, str]) -> dict:
    """未知表单的启发式投影：按标签优先级猜 标题/部门/提交时间/状态。

    标题候选标签依次匹配：标题/名称 → 问题 → 主题 → 内容；都没有则用首个非空文本字段。
    """
    proj = {"title": "", "status": "", "owner": "", "dept": "", "due_time": "", "submit_time": ""}
    items = [(labels.get(w, ""), v) for w, v in fields.items()]

    def _first(*keywords: str) -> str:
        for kw in keywords:
            for label, value in items:
                if kw in label:
                    v = str(_jdy_scalar(value) or "").strip()
                    if v:
                        return v
        return ""

    proj["title"] = _first("标题", "名称", "问题", "主题", "内容")
    proj["status"] = _first("状态")[:32]
    proj["dept"] = _first("部门")[:64]
    proj["owner"] = _first("负责", "提交人", "创建人")[:128]
    proj["submit_time"] = _first("提交时间", "创建时间")[:32]
    if not proj["title"]:
        for label, value in items:
            v = str(_jdy_scalar(value) or "").strip()
            if v and label and "时间" not in label:
                proj["title"] = v[:250]
                break
    return proj


def sync_entry(db: Session, kind: str) -> dict:
    """同步单个表单：全量拉取 → upsert → （未截断时）prune → 写同步日志。"""
    started = time.monotonic()
    entry_id = configured_entries().get(kind, "")
    label = KIND_LABELS.get(kind, kind)
    log = JdySyncLog(scope=kind, status="success")
    stats = {"kind": kind, "entry_id": entry_id}

    def _finish(status: str, message: str, items: int = 0, created: int = 0,
                updated: int = 0, pruned: int = 0, truncated: bool = False) -> dict:
        log.status = status
        log.message = message[:500]
        log.items = items
        log.created_n = created
        log.updated_n = updated
        log.pruned_n = pruned
        log.truncated = truncated
        log.duration_ms = int((time.monotonic() - started) * 1000)
        db.add(log)
        db.commit()
        stats.update(status=status, message=log.message, items=items,
                     created=created, updated=updated, pruned=pruned, truncated=truncated)
        return stats

    if jdy.mock:
        return _finish("skipped", "JDY 为 MOCK 模式（未配置凭证），跳过同步")
    if not entry_id:
        return _finish("skipped", f"表单未配置 entry_id（{label}），跳过")

    try:
        labels = jdy.list_widgets(entry_id)  # 标签失败不阻断（返回 {}）
        rows = jdy.query_form(entry_id, limit=100,
                              max_pages=get_settings().jdy_sync_max_pages)
        truncated = jdy.last_truncated
    except Exception as e:  # noqa: BLE001 — 网络/接口异常收敛为失败日志，保旧镜像
        return _finish("failed", f"拉取失败：{type(e).__name__}: {e}")

    seen_ids: list[str] = []
    created = updated = 0
    for row in rows:
        data_id = str(row.get("_id") or "")
        if not data_id:
            continue
        seen_ids.append(data_id)
        fields = {k: v for k, v in row.items()}
        proj = _clamp_proj(
            _project_task(fields) if kind == "task" else _project_generic(fields, labels))
        if not proj["title"]:
            proj["title"] = f"（无标题记录 {data_id[-6:]}）"
        raw = {"_fields": fields, "_labels": labels}
        existing = db.execute(
            select(JdyRecord).where(JdyRecord.entry_id == entry_id,
                                    JdyRecord.data_id == data_id)
        ).scalar_one_or_none()
        if existing:
            for k, v in proj.items():
                setattr(existing, k, v)
            existing.raw = raw
            existing.synced_at = datetime.utcnow()
            updated += 1
        else:
            db.add(JdyRecord(entry_id=entry_id, data_id=data_id, kind=kind, raw=raw, **proj))
            created += 1

    pruned = 0
    if truncated:
        # 截断数据不完整，禁止 prune（防误删）；日志标注
        pass
    else:
        q = delete(JdyRecord).where(JdyRecord.entry_id == entry_id)
        if seen_ids:
            q = q.where(JdyRecord.data_id.not_in(seen_ids))
        pruned = db.execute(q).rowcount or 0

    msg = f"{label}：同步 {len(rows)} 条（新增 {created} / 更新 {updated} / 删除 {pruned}）"
    if truncated:
        msg += f"；已达 max_pages 上限截断，跳过删除校验"
    return _finish("success", msg, items=len(rows), created=created,
                   updated=updated, pruned=pruned, truncated=truncated)


def run_full_sync(db: Session, actor_user_id: int | None = None) -> dict:
    """全量同步所有已配置表单。单表单失败不中断其余（错误隔离）。"""
    entries = configured_entries()
    results: dict[str, dict] = {}
    for kind in entries:
        try:
            results[kind] = sync_entry(db, kind)
        except Exception as e:  # noqa: BLE001 — 单表单失败隔离
            db.rollback()
            log = JdySyncLog(scope=kind, status="failed",
                             message=f"同步异常：{type(e).__name__}: {e}"[:500])
            db.add(log)
            db.commit()
            results[kind] = {"kind": kind, "status": "failed", "message": log.message}
    if not entries:
        results["_"] = {"status": "skipped", "message": "未配置任何表单 entry_id"}
    ok = all(r.get("status") in ("success", "skipped") for r in results.values())
    db.add(AuditLog(user_id=actor_user_id, action="jdy.sync", resource="jdy",
                    detail={"manual": actor_user_id is not None,
                            "results": {k: {kk: r.get(kk) for kk in ("status", "items", "message")}
                                        for k, r in results.items()}}))
    db.commit()
    return {"ok": ok, "entries": results, "at": datetime.utcnow().isoformat()}
