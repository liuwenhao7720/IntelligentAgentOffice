# -*- coding: utf-8 -*-
"""_patch_today.py —— 「今日工作安排」前后端改造补丁（对应手册 1.5，首页默认展示）。

覆盖缺口：
  后端
    B1 TaskItem 补列 is_meeting / is_other_request / is_today_fixed + 轻量迁移（1.5 B0 固定会议）
    B2 capture_natural 启发式识别会议与固定时间点（1.5 口头录入）
    B3 capture_with_llm 抽取字段补 ai_fixed_start / is_meeting / is_other_request（1.5）
    B4 tasks_capture / tasks_ingest / tasks_feedback 补审计；ingest/today 透传新字段（非功能-日志）
    B5 新增 POST /tasks/{id}/status 完成/重开；feedback 支持 due_time 改期（1.5 溢出→改期/明日优先）
    B6 早宣稿一键入池：POST /briefings/morning 支持 ingest=true（1.5 与早宣的关系）
    B7 main.py 启动时执行 migrate_db()
  前端
    F1 新增「今日工作安排」Tab 并设为首页默认（1.5 首句）
    F2 口语录入 → 候选确认 → 入池（1.5）
    F3 B0–B4 时间轴 + 溢出区（改期/明日优先）+ 领导模式开关（1.5）
    F4 样式
用法：python3 _patch_today.py   （幂等，重复执行跳过已应用项）
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APPLIED = []


def patch_file(rel: str, pairs: list[tuple[str, str, str]]) -> None:
    p = ROOT / rel
    text = p.read_text(encoding="utf-8")
    for name, old, new in pairs:
        marker = new[:60]
        if marker in text:
            print(f"  [skip] {rel} :: {name}（已应用）")
            continue
        assert old in text, f"锚点未命中: {rel} :: {name}\n---锚点---\n{old[:200]}"
        text = text.replace(old, new, 1)
        APPLIED.append(f"{rel} :: {name}")
    p.write_text(text, encoding="utf-8")


# ============================== B1 数据库：补列 + 迁移 ==============================
patch_file("app/database.py", [(
    "B1-TaskItem补三列",
    """    ai_leader_assigned = Column(Boolean, default=False)
    ai_blocking_others = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExportCheck(Base):""",
    """    ai_leader_assigned = Column(Boolean, default=False)
    ai_blocking_others = Column(Boolean, default=False)
    # 今日工作安排三态标记（手册 1.5：B0 固定会议 / 他人要求 / 今日固定）
    is_meeting = Column(Boolean, default=False)
    is_other_request = Column(Boolean, default=False)
    is_today_fixed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExportCheck(Base):""",
)])

patch_file("app/database.py", [(
    "B1-轻量迁移函数",
    """def ping_db() -> bool:""",
    '''def migrate_db() -> None:
    """轻量迁移：为已存在的 task_items 表补充新增列（create_all 不会 ALTER）。

    幂等：按 information_schema/PRAGMA 检查后再 ADD COLUMN；SQLite 与 PostgreSQL 通用。
    """
    from sqlalchemy import inspect, text

    insp = inspect(_engine)
    if "task_items" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("task_items")}
    bool_default = "FALSE" if _engine.dialect.name == "postgresql" else "0"
    for col in ("is_meeting", "is_other_request", "is_today_fixed"):
        if col in existing:
            continue
        with _engine.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE task_items ADD COLUMN {col} BOOLEAN DEFAULT {bool_default}"
            ))
        print(f"[migrate] task_items +{col}")


def ping_db() -> bool:''',
)])

# ============================== B7 启动时迁移 ==============================
patch_file("app/main.py", [(
    "B7-import",
    "from .database import SessionLocal, init_db",
    "from .database import SessionLocal, init_db, migrate_db",
), (
    "B7-调用",
    """            init_db()
            break""",
    """            init_db()
            migrate_db()
            break""",
)])

# ============================== B2/B3 采集增强 ==============================
patch_file("app/services/task_agent.py", [(
    "B2-classify_task括号显式化",
    """    if fixed or is_meeting or leader or t.get("is_other_request") or assignee_today and t.get("is_today_fixed"):
        return TYPE_FIXED""",
    """    if fixed or is_meeting or leader or t.get("is_other_request") or (assignee_today and t.get("is_today_fixed")):
        return TYPE_FIXED""",
), (
    "B2-会议与固定时间正则常量",
    """def capture_natural(text: str, source: str = "manual", owner: str = "") -> dict:""",
    '''# 会议/固定事项识别（手册 1.5：B0 固定会议不可打乱）
_MEETING_RE = re.compile(r"(会议|例会|晨会|早会|周会|月会|评审会|协调会|交班会|电话会|视频会|腾讯会议|zoom|teams)", re.I)
_TIME_RE = re.compile(r"(上午|下午|中午|晚上|今早|明早)?\\s*(\\d{1,2})\\s*[:：点]\\s*(\\d{1,2})?")


def _guess_fixed_time(text: str) -> str:
    """从口语中抽取固定时间点，返回 HH:MM；无则空串。"""
    m = _TIME_RE.search(text)
    if not m:
        return ""
    period, hh, mm = m.group(1) or "", int(m.group(2)), m.group(3)
    minute = int(mm) if mm else 0
    if period in ("下午", "晚上") and hh < 12:
        hh += 12
    if period == "中午" and hh < 12:
        hh = 12 if hh == 12 else hh
    if not (0 <= hh <= 23 and 0 <= minute <= 59):
        return ""
    return f"{hh:02d}:{minute:02d}"


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "是")


def capture_natural(text: str, source: str = "manual", owner: str = "") -> dict:''',
), (
    "B2-capture_natural识别会议",
    """    for i, p in enumerate(parts[:20]):
        due = _guess_due(p)
        candidates.append({
            "title": p[:80],
            "description": p,
            "source": source,
            "owner": owner,
            "due_time": due,
            "estimated_hours": 2.0,
            "ai_urgency": 4 if due else 3,
            "ai_importance": 3,
            "ai_complexity": 3,
            "ai_impact_scope": "个人",
            "ai_dedup_key": _dedup_key(p),
            "created_today": True,
            "confidence": 0.6,
        })""",
    """    for i, p in enumerate(parts[:20]):
        due = _guess_due(p)
        is_meeting = bool(_MEETING_RE.search(p))
        fixed_time = _guess_fixed_time(p)
        candidates.append({
            "title": p[:80],
            "description": p,
            "source": source,
            "owner": owner,
            "due_time": due,
            "estimated_hours": 1.0 if is_meeting else 2.0,
            "ai_urgency": 4 if (due or fixed_time) else 3,
            "ai_importance": 3,
            "ai_complexity": 3,
            "ai_impact_scope": "个人",
            "is_meeting": is_meeting,
            "ai_fixed_start": fixed_time,
            "ai_dedup_key": _dedup_key(p),
            "created_today": True,
            "confidence": 0.6,
        })""",
), (
    "B3-LLM提示词补字段",
    """        "estimated_hours(数字), ai_urgency(1-5), ai_importance(1-5), ai_complexity(1-5), "
        "ai_impact_scope(个人/他人/部门/公司/生产采购), ai_leader_assigned(bool)。\\n"
        "禁止编造不存在的任务。\\n\\n输入：\\n" + text[:3000]""",
    """        "estimated_hours(数字), ai_urgency(1-5), ai_importance(1-5), ai_complexity(1-5), "
        "ai_impact_scope(个人/他人/部门/公司/生产采购), ai_leader_assigned(bool), "
        "is_meeting(bool，是否为会议), ai_fixed_start(HH:MM可空，仅当有明确时间点), "
        "is_other_request(bool，是否他人临时要求)。\\n"
        "禁止编造不存在的任务。\\n\\n输入：\\n" + text[:3000]""",
), (
    "B3-LLM结果布尔归一",
    """                it["source"] = source
                it["owner"] = owner
                it["created_today"] = True
                it["ai_dedup_key"] = _dedup_key(it.get("title", ""))
                candidates.append(it)""",
    """                it["source"] = source
                it["owner"] = owner
                it["created_today"] = True
                it["is_meeting"] = _as_bool(it.get("is_meeting"))
                it["is_other_request"] = _as_bool(it.get("is_other_request"))
                it["ai_leader_assigned"] = _as_bool(it.get("ai_leader_assigned"))
                it["ai_dedup_key"] = _dedup_key(it.get("title", ""))
                candidates.append(it)""",
)])

print("后端 B1/B2/B3/B7 完成")

# ============================== B4/B5/B6 路由 ==============================
patch_file("app/routers/api.py", [(
    "B4-capture补审计",
    '''@router.post("/tasks/capture")
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
    return result''',
    '''@router.post("/tasks/capture")
def tasks_capture(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
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
    _audit(db, user, "task.capture", "task", count=result.get("count", 0),
           source=body.get("source", "manual"))
    return result''',
), (
    "B4-ingest补三态字段",
    """            ai_leader_assigned=bool(it.get("ai_leader_assigned")),
            ai_blocking_others=bool(it.get("ai_blocking_others")),
        )""",
    """            ai_leader_assigned=bool(it.get("ai_leader_assigned")),
            ai_blocking_others=bool(it.get("ai_blocking_others")),
            is_meeting=bool(it.get("is_meeting")),
            is_other_request=bool(it.get("is_other_request")),
            is_today_fixed=bool(it.get("is_today_fixed")),
        )""",
), (
    "B4-ingest补审计",
    """        db.add(row)
        created += 1
    db.commit()
    return {"created": created, "skipped_dup": skipped}""",
    """        db.add(row)
        created += 1
    db.commit()
    _audit(db, user, "task.ingest", "task", created=created, skipped_dup=skipped)
    return {"created": created, "skipped_dup": skipped}""",
), (
    "B4-today透传三态与评分",
    """        "ai_leader_assigned": r.ai_leader_assigned,
        "ai_blocking_others": r.ai_blocking_others,
        "ai_source_type": r.ai_source_type,
        "source": r.source,
        "project_name": r.project_name,""",
    """        "ai_leader_assigned": r.ai_leader_assigned,
        "ai_blocking_others": r.ai_blocking_others,
        "is_meeting": bool(getattr(r, "is_meeting", False)),
        "is_other_request": bool(getattr(r, "is_other_request", False)),
        "is_today_fixed": bool(getattr(r, "is_today_fixed", False)),
        "ai_priority_score": r.ai_priority_score,
        "description": r.description or "",
        "ai_source_type": r.ai_source_type,
        "source": r.source,
        "project_name": r.project_name,""",
), (
    "B5-feedback支持改期+审计",
    """    if body.get("ai_fixed_start"):
        row.ai_fixed_start = body["ai_fixed_start"]
    db.commit()
    return {"ok": True}""",
    """    if body.get("ai_fixed_start"):
        row.ai_fixed_start = body["ai_fixed_start"]
    if body.get("due_time"):
        row.due_time = str(body["due_time"])[:32]
    db.commit()
    _audit(db, user, "task.feedback", f"task:{task_id}", **{k: v for k, v in body.items() if isinstance(v, (str, int, float, bool))})
    return {"ok": True}""",
), (
    "B6-早宣一键入池",
    '''@router.post("/briefings/morning")
def api_morning(body: dict, user: User = Depends(current_user)):
    data = build_morning_plan(
        name=user.name,
        dept=user.department,
        tasks_raw=body.get("tasks_raw", ""),
        focus=body.get("focus", ""),
        blockers=body.get("blockers", ""),
    )
    return data''',
    '''@router.post("/briefings/morning")
def api_morning(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = build_morning_plan(
        name=user.name,
        dept=user.department,
        tasks_raw=body.get("tasks_raw", ""),
        focus=body.get("focus", ""),
        blockers=body.get("blockers", ""),
    )
    # 手册 1.5「与早宣的关系」：早宣说计划，今日安排帮你把计划排进一天
    # ingest=true 时把口述任务同步拆解入池（与 /tasks/ingest 同一去重逻辑）
    if body.get("ingest") and body.get("tasks_raw", "").strip():
        cap = (
            capture_with_llm(body["tasks_raw"], source="morning_briefing", owner=user.name)
            if body.get("use_llm", True) else
            capture_natural(body["tasks_raw"], source="morning_briefing", owner=user.name)
        )
        res = tasks_ingest({"items": cap.get("candidates", [])}, db=db, user=user)
        data["ingested"] = res
    _audit(db, user, "briefing.morning", "briefing", ingested=bool(body.get("ingest")))
    return data''',
)])

# B5 新增状态端点（追加到文件末尾）
api_path = ROOT / "app/routers/api.py"
api_text = api_path.read_text(encoding="utf-8")
if "tasks_set_status" not in api_text:
    api_text += '''

@router.post("/tasks/{task_id}/status")
def tasks_set_status(task_id: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """任务状态流转（手册 1.5：今日安排上的完成/重开）。"""
    row = db.get(TaskItem, task_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    status = (body.get("status") or "").strip()
    if status not in ("待办", "进行中", "已完成", "已验收"):
        raise HTTPException(422, "status 必须是 待办/进行中/已完成/已验收")
    row.status = status
    db.commit()
    _audit(db, user, "task.status", f"task:{task_id}", status=status)
    return {"ok": True, "status": status}
'''
    api_path.write_text(api_text, encoding="utf-8")
    APPLIED.append("app/routers/api.py :: B5-状态端点")

print("后端 B4/B5/B6 完成")
print("已应用:", len(APPLIED), "项")
for a in APPLIED:
    print("  +", a)
