# -*- coding: utf-8 -*-
"""简道云本地镜像读取 API（单向拉取的读侧）。

数据流：JDY --poller--> jdy_records（本地镜像）--> 本模块 API --> 前端浏览。
web 端只读本地库，不打 JDY API；手动触发同步与日志查看限 admin/manager（jdy.sync 权限点）。
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import current_user, require_perm
from ..database import JdyRecord, JdySyncLog, User, get_db
from ..services.jdy import WIDGET_LABEL_FALLBACK, jdy
from ..services.jdy_sync import KIND_LABELS, configured_entries, run_full_sync
from ..services.task_agent import _jdy_scalar

router = APIRouter()

# 时间段口径：今天/昨天/本周(周一~周日)/上周/本月/全部
_PERIOD_KEYS = ("today", "yesterday", "this_week", "last_week", "this_month", "all")
# 时间段所基于的日期口径：截止时间 due_time / 开始·提交时间 submit_time
_DATE_FIELD_COLS = {"due": JdyRecord.due_time, "submit": JdyRecord.submit_time}


def _period_range(period: str) -> tuple[date | None, date | None]:
    """period → (起, 止) 含端点的本地日期区间；all → (None, None) 不过滤。

    与 briefing 模块一致使用服务器本地日期 date.today()（部署侧建议 TZ=Asia/Shanghai）。
    """
    today = date.today()
    if period == "today":
        return today, today
    if period == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if period == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if period == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6)
    if period == "this_month":
        start = today.replace(day=1)
        end = (date(today.year + 1, 1, 1) if today.month == 12
               else date(today.year, today.month + 1, 1)) - timedelta(days=1)
        return start, end
    return None, None  # all


def _check_kind(kind: str) -> str:
    if kind not in KIND_LABELS:
        raise HTTPException(422, f"未知表单类型：{kind}（支持 {list(KIND_LABELS)}）")
    return kind


def _friendly_fields(rec: JdyRecord) -> dict[str, str]:
    """raw 的 widget 原文 → {中文标签: 归一化值}。

    标签优先级：同步时拉取的表单配置（_labels）→ 任务表静态映射兜底 → widget id。
    """
    raw = rec.raw or {}
    fields = raw.get("_fields") or {}
    labels = raw.get("_labels") or {}
    out: dict[str, str] = {}
    for widget, value in fields.items():
        if widget == "_id":
            continue
        label = labels.get(widget) or WIDGET_LABEL_FALLBACK.get(widget) or widget
        v = _jdy_scalar(value)
        out[label] = "" if v is None else str(v)
    return out


def _record_item(rec: JdyRecord) -> dict:
    return {
        "data_id": rec.data_id,
        "kind": rec.kind,
        "title": rec.title,
        "status": rec.status,
        "owner": rec.owner,
        "dept": rec.dept,
        "due_time": rec.due_time,
        "submit_time": rec.submit_time,
        "synced_at": rec.synced_at.isoformat() if rec.synced_at else None,
    }


@router.get("/jdy/overview")
def jdy_overview(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """镜像概览：各表单记录数 / 最近同步时间 / mock 与配置状态（全体登录用户可读）。"""
    entries = configured_entries()
    forms = []
    for kind, label in KIND_LABELS.items():
        entry_id = entries.get(kind, "")
        count = 0
        last_sync = None
        if entry_id:
            count = db.execute(
                select(func.count()).select_from(JdyRecord).where(JdyRecord.kind == kind)
            ).scalar() or 0
            last_sync = db.execute(
                select(func.max(JdyRecord.synced_at)).where(JdyRecord.kind == kind)
            ).scalar()
        last_log = db.execute(
            select(JdySyncLog).where(JdySyncLog.scope == kind)
            .order_by(JdySyncLog.id.desc()).limit(1)
        ).scalar_one_or_none()
        forms.append({
            "kind": kind,
            "label": label,
            "entry_configured": bool(entry_id),
            "records": count,
            "last_sync": last_sync.isoformat() if last_sync else None,
            "last_status": last_log.status if last_log else "",
            "last_message": last_log.message if last_log else "",
        })
    return {
        "mock": jdy.mock,
        "sync_enabled": jdy.mock is False,
        "forms": forms,
        "hint": "" if not jdy.mock else "JDY 为 MOCK 模式：配置 JDY_APP_ID/JDY_API_KEY 后由 poller 周期拉取",
    }


@router.get("/jdy/depts")
def jdy_dept_options(kind: str = "task",
                     db: Session = Depends(get_db), user: User = Depends(current_user)):
    """部门下拉选项：镜像数据 dept 列去重，并按逗号拆分为原子部门（如「市场部,项目部」→ 两项）。

    数据驱动（与简道云实际值一致），无需维护静态部门表；按 dept 升序返回。
    """
    kind = _check_kind(kind)
    rows = db.execute(
        select(JdyRecord.dept).where(JdyRecord.kind == kind, JdyRecord.dept != "").distinct()
    ).scalars().all()
    depts: set[str] = set()
    for raw in rows:
        for part in str(raw).replace("，", ",").split(","):
            part = part.strip()
            if part:
                depts.add(part)
    return {"kind": kind, "depts": sorted(depts)}


@router.get("/jdy/data/{kind}")
def jdy_data_list(kind: str, q: str = "", limit: int = 100, offset: int = 0,
                  period: str = "all", date_field: str = "due", person: str = "",
                  dept: str = "",
                  db: Session = Depends(get_db), user: User = Depends(current_user)):
    """镜像列表读侧。

    过滤参数（均可选，缺省不过滤、保持旧契约）：
    - period：today/yesterday/this_week/last_week/this_month/all，时间段区间含端点；
    - date_field：due（截止时间 due_time，默认）/ submit（开始·提交时间 submit_time）；
    - person：个人名称或部门名称关键字（owner/dept 模糊包含，OR 关系）；
    - dept：部门下拉精确维度（dept 列包含匹配，组合部门记录按原子部门命中）；
    - limit/offset：分页（limit ≤ 200）。

    后续「只看本人」可由前端传 person=当前用户姓名/部门实现，登录信息已具备（user.name/department）。
    注意：日期为空的记录只在 period=all 时出现。
    """
    kind = _check_kind(kind)
    limit = min(max(1, limit), 200)
    if period not in _PERIOD_KEYS:
        raise HTTPException(422, f"未知时间段：{period}（支持 {list(_PERIOD_KEYS)}）")
    if date_field not in _DATE_FIELD_COLS:
        raise HTTPException(422, f"未知日期口径：{date_field}（支持 {list(_DATE_FIELD_COLS)}）")
    stmt = select(JdyRecord).where(JdyRecord.kind == kind)
    if q.strip():
        stmt = stmt.where(JdyRecord.title.contains(q.strip()))
    start, end = _period_range(period)
    if start is not None:
        # 镜像日期为字符串（ISO 或纯日期），统一按 YYYY-MM-DD 前缀做区间比较，兼容两种格式
        day_col = func.substr(_DATE_FIELD_COLS[date_field], 1, 10)
        stmt = stmt.where(day_col >= start.isoformat(), day_col <= end.isoformat())
    if person.strip():
        p = person.strip()
        stmt = stmt.where(or_(JdyRecord.owner.contains(p), JdyRecord.dept.contains(p)))
    if dept.strip():
        stmt = stmt.where(JdyRecord.dept.contains(dept.strip()))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = db.execute(
        stmt.order_by(JdyRecord.synced_at.desc()).offset(max(0, offset)).limit(limit)
    ).scalars().all()
    return {"kind": kind, "label": KIND_LABELS[kind], "total": total,
            "limit": limit, "offset": max(0, offset),
            "filters": {"q": q.strip(), "period": period, "date_field": date_field,
                        "person": person.strip(), "dept": dept.strip()},
            "items": [_record_item(r) for r in rows], "mock": jdy.mock}


@router.get("/jdy/data/{kind}/{data_id}")
def jdy_data_detail(kind: str, data_id: str,
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    kind = _check_kind(kind)
    rec = db.execute(
        select(JdyRecord).where(JdyRecord.kind == kind, JdyRecord.data_id == data_id)
    ).scalar_one_or_none()
    if not rec:
        raise HTTPException(404, "记录不存在（或尚未同步）")
    return {**_record_item(rec), "fields": _friendly_fields(rec)}


@router.post("/jdy/sync")
def jdy_sync_now(db: Session = Depends(get_db), user: User = Depends(require_perm("jdy.sync"))):
    """手动触发全量同步（admin/manager）。返回本轮各表单统计。"""
    return run_full_sync(db, actor_user_id=user.id)


@router.get("/jdy/sync/logs")
def jdy_sync_logs(limit: int = 20,
                  db: Session = Depends(get_db), user: User = Depends(require_perm("jdy.sync"))):
    rows = db.execute(
        select(JdySyncLog).order_by(JdySyncLog.id.desc()).limit(min(max(1, limit), 100))
    ).scalars().all()
    return [{
        "id": r.id, "scope": r.scope, "status": r.status, "message": r.message,
        "items": r.items, "created_n": r.created_n, "updated_n": r.updated_n,
        "pruned_n": r.pruned_n, "truncated": r.truncated, "duration_ms": r.duration_ms,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
