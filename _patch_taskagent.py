# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")

p = ROOT / "app" / "database.py"
t = p.read_text(encoding="utf-8")
if "class TaskItem" not in t:
    block = '''class TaskItem(Base):
    """任务池（简道云镜像 + AI 扩展字段，见《任务管理智能体落地实施方案》3.3）。"""
    __tablename__ = "task_items"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    external_task_no = Column(String(64), default="")
    title = Column(String(256))
    description = Column(Text, default="")
    project_name = Column(String(128), default="")
    status = Column(String(32), default="待办")
    start_time = Column(String(32), default="")
    due_time = Column(String(32), default="")
    estimated_hours = Column(Float, default=1.0)
    priority = Column(String(16), default="中")
    source = Column(String(32), default="manual")
    ai_source_type = Column(String(32), default="new_input")
    ai_urgency = Column(Integer, default=3)
    ai_importance = Column(Integer, default=3)
    ai_value = Column(String(16), default="中")
    ai_impact_scope = Column(String(16), default="个人")
    ai_complexity = Column(Integer, default=3)
    ai_dependency_ids = Column(JSON, default=list)
    ai_fixed_start = Column(String(32), default="")
    ai_fixed_end = Column(String(32), default="")
    ai_priority_score = Column(Float, default=0.0)
    ai_schedule_block = Column(JSON, default=dict)
    ai_remind_policy = Column(JSON, default=dict)
    ai_dedup_key = Column(String(64), default="", index=True)
    ai_confidence = Column(Float, default=0.5)
    ai_user_feedback = Column(JSON, default=dict)
    ai_leader_assigned = Column(Boolean, default=False)
    ai_blocking_others = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExportCheck(Base):'''
    t = t.replace("class ExportCheck(Base):", block, 1)
    p.write_text(t, encoding="utf-8")
    print("TaskItem added")
else:
    print("TaskItem exists")

# API routes
p = ROOT / "app" / "routers" / "api.py"
t = p.read_text(encoding="utf-8")
if "/tasks/today" not in t:
    t = t.replace(
        "from ..database import ExportCheck, Scenario, TaskProject",
        "from ..database import ExportCheck, Scenario, TaskItem, TaskProject",
    )
    t = t.replace(
        "from ..services.mature_rules import",
        "from ..services.task_agent import (\n"
        "    AI_EXT_FIELDS, JDY_FIELD_MAP, capture_natural, capture_with_llm,\n"
        "    classify_task, plan_today, score_task,\n"
        ")\n"
        "from ..services.mature_rules import",
    )
    t = t.rstrip() + '''

# ---------- 任务管理智能体 P0：今日工作安排 ----------
@router.post("/tasks/capture")
def tasks_capture(body: dict, user: User = Depends(current_user)):
    """自然语言采集任务（口头/聊天/邮件片段）。"""
    text = body.get("text") or ""
    if not text.strip():
        raise HTTPException(422, "缺少 text")
    use_llm = bool(body.get("use_llm", True))
    result = (
        capture_with_llm(text, source=body.get("source", "manual"), owner=user.name)
        if use_llm else
        capture_natural(text, source=body.get("source", "manual"), owner=user.name)
    )
    return result


@router.post("/tasks/ingest")
def tasks_ingest(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """确认采纳采集结果 → 写入任务池（去重）。"""
    items = body.get("items") or []
    created = 0
    skipped = 0
    for it in items:
        key = it.get("ai_dedup_key") or (it.get("title") or "")[:64]
        exists = db.execute(
            select(TaskItem).where(TaskItem.user_id == user.id, TaskItem.ai_dedup_key == key)
        ).scalar_one_or_none()
        if exists:
            skipped += 1
            continue
        row = TaskItem(
            user_id=user.id,
            title=it.get("title", "")[:250],
            description=it.get("description", ""),
            project_name=it.get("project_name", ""),
            due_time=it.get("due_time") or "",
            start_time=it.get("start_time") or "",
            estimated_hours=float(it.get("estimated_hours") or 1),
            priority=it.get("priority", "中"),
            source=it.get("source", "manual"),
            ai_source_type=it.get("ai_source_type") or classify_task(it),
            ai_urgency=int(it.get("ai_urgency") or 3),
            ai_importance=int(it.get("ai_importance") or 3),
            ai_value=it.get("ai_value", "中"),
            ai_impact_scope=it.get("ai_impact_scope", "个人"),
            ai_complexity=int(it.get("ai_complexity") or 3),
            ai_fixed_start=it.get("ai_fixed_start") or "",
            ai_dedup_key=key,
            ai_confidence=float(it.get("confidence") or it.get("ai_confidence") or 0.5),
            ai_leader_assigned=bool(it.get("ai_leader_assigned")),
            ai_blocking_others=bool(it.get("ai_blocking_others")),
        )
        row.ai_priority_score = score_task({
            "due_time": row.due_time,
            "ai_importance": row.ai_importance,
            "ai_urgency": row.ai_urgency,
            "ai_impact_scope": row.ai_impact_scope,
            "estimated_hours": row.estimated_hours,
            "ai_complexity": row.ai_complexity,
            "ai_blocking_others": row.ai_blocking_others,
            "ai_leader_assigned": row.ai_leader_assigned,
        })
        db.add(row)
        created += 1
    db.commit()
    return {"created": created, "skipped_dup": skipped}


@router.get("/tasks/today")
def tasks_today(
    leader_mode: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """首页「今日工作安排」：三分类 + 排序 + 时间轴。"""
    rows = db.execute(select(TaskItem).where(TaskItem.user_id == user.id)).scalars().all()
    tasks = [{
        "id": r.id,
        "title": r.title,
        "status": r.status,
        "due_time": r.due_time,
        "start_time": r.start_time,
        "estimated_hours": r.estimated_hours,
        "ai_importance": r.ai_importance,
        "ai_urgency": r.ai_urgency,
        "ai_complexity": r.ai_complexity,
        "ai_impact_scope": r.ai_impact_scope,
        "ai_fixed_start": r.ai_fixed_start,
        "ai_leader_assigned": r.ai_leader_assigned,
        "ai_blocking_others": r.ai_blocking_others,
        "ai_source_type": r.ai_source_type,
        "source": r.source,
        "project_name": r.project_name,
    } for r in rows if r.status not in ("已完成", "已验收")]
    plan = plan_today(tasks, leader_mode=leader_mode)
    return plan


@router.get("/tasks/field-map")
def tasks_field_map(user: User = Depends(current_user)):
    """简道云字段映射 + AI 扩展字段清单（供开发/运维对齐）。"""
    return {
        "jdy_task_fields": JDY_FIELD_MAP,
        "ai_extension_fields": AI_EXT_FIELDS,
        "note": "开发前须向简道云管理员获取表单 API 名称、表单 ID、权限与写回能力",
    }


@router.post("/tasks/{task_id}/feedback")
def tasks_feedback(task_id: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """用户调整反馈（排序学习，P1）。"""
    row = db.get(TaskItem, task_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    fb = dict(row.ai_user_feedback or {})
    fb[datetime.utcnow().isoformat()] = body
    row.ai_user_feedback = fb
    if body.get("ai_importance"):
        row.ai_importance = int(body["ai_importance"])
    if body.get("ai_urgency"):
        row.ai_urgency = int(body["ai_urgency"])
    if body.get("ai_impact_scope"):
        row.ai_impact_scope = body["ai_impact_scope"]
    if body.get("ai_fixed_start"):
        row.ai_fixed_start = body["ai_fixed_start"]
    db.commit()
    return {"ok": True}
'''
    p.write_text(t, encoding="utf-8")
    print("api routes added")
else:
    print("api already has tasks")

print("done")
