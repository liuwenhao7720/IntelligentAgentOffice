# -*- coding: utf-8 -*-
"""_patch_today_fix.py —— 修正版：补齐 _patch_today.py 中被幂等误判跳过的替换。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def rep(rel, name, old, new):
    p = ROOT / rel
    text = p.read_text(encoding="utf-8")
    if old in text:
        text = text.replace(old, new, 1)
        p.write_text(text, encoding="utf-8")
        print(f"  [ok]   {rel} :: {name}")
    elif new[:80] in text:
        print(f"  [skip] {rel} :: {name}（已应用）")
    else:
        raise AssertionError(f"锚点未命中: {rel} :: {name}")


# 1) database.py B1 补三列（migrate_db 已应用，列定义缺失）
rep("app/database.py", "B1-TaskItem补三列",
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


class ExportCheck(Base):""")

# 2) task_agent.py B2 括号显式化
rep("app/services/task_agent.py", "B2-classify括号",
    "or assignee_today and t.get(\"is_today_fixed\"):",
    "or (assignee_today and t.get(\"is_today_fixed\")):")

# 3) task_agent.py B2 capture_natural 会议识别
rep("app/services/task_agent.py", "B2-capture_natural会议识别",
    """    for i, p in enumerate(parts[:20]):
        due = _guess_due(p)
        candidates.append({
            "title": p[:80],
            "description": p,
            "source": source,
            "owner": owner,
            "due_time": due,
            "estimated_hours": 2.0,
            "ai_urgency": 4 if due else 3,""",
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
            "ai_urgency": 4 if (due or fixed_time) else 3,""")

# capture_natural 候选补 is_meeting/ai_fixed_start 键
rep("app/services/task_agent.py", "B2-候选补键",
    """            "ai_impact_scope": "个人",
            "ai_dedup_key": _dedup_key(p),""",
    """            "ai_impact_scope": "个人",
            "is_meeting": is_meeting,
            "ai_fixed_start": fixed_time,
            "ai_dedup_key": _dedup_key(p),""")

# 4) task_agent.py B3 LLM 提示词补字段
rep("app/services/task_agent.py", "B3-LLM提示词",
    '''        "ai_impact_scope(个人/他人/部门/公司/生产采购), ai_leader_assigned(bool)。\\n"
        "禁止编造不存在的任务。\\n\\n输入：\\n" + text[:3000]''',
    '''        "ai_impact_scope(个人/他人/部门/公司/生产采购), ai_leader_assigned(bool), "
        "is_meeting(bool，是否为会议), ai_fixed_start(HH:MM可空，仅当有明确时间点), "
        "is_other_request(bool，是否他人临时要求)。\\n"
        "禁止编造不存在的任务。\\n\\n输入：\\n" + text[:3000]''')

# 5) task_agent.py B3 LLM 结果布尔归一
rep("app/services/task_agent.py", "B3-布尔归一",
    """                it["created_today"] = True
                it["ai_dedup_key"] = _dedup_key(it.get("title", ""))""",
    """                it["created_today"] = True
                it["is_meeting"] = _as_bool(it.get("is_meeting"))
                it["is_other_request"] = _as_bool(it.get("is_other_request"))
                it["ai_leader_assigned"] = _as_bool(it.get("ai_leader_assigned"))
                it["ai_dedup_key"] = _dedup_key(it.get("title", ""))""")

# 6) api.py B4 capture 审计
rep("app/routers/api.py", "B4-capture审计",
    '''@router.post("/tasks/capture")
def tasks_capture(body: dict, user: User = Depends(current_user)):''',
    '''@router.post("/tasks/capture")
def tasks_capture(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):''')
rep("app/routers/api.py", "B4-capture审计调用",
    """        capture_natural(text, source=body.get("source", "manual"), owner=user.name)
    )
    return result


@router.post("/tasks/ingest")""",
    """        capture_natural(text, source=body.get("source", "manual"), owner=user.name)
    )
    _audit(db, user, "task.capture", "task", count=result.get("count", 0),
           source=body.get("source", "manual"))
    return result


@router.post("/tasks/ingest")""")

# 7) api.py B4 ingest 三态字段 + 审计
rep("app/routers/api.py", "B4-ingest三态",
    """            ai_leader_assigned=bool(it.get("ai_leader_assigned")),
            ai_blocking_others=bool(it.get("ai_blocking_others")),
        )""",
    """            ai_leader_assigned=bool(it.get("ai_leader_assigned")),
            ai_blocking_others=bool(it.get("ai_blocking_others")),
            is_meeting=bool(it.get("is_meeting")),
            is_other_request=bool(it.get("is_other_request")),
            is_today_fixed=bool(it.get("is_today_fixed")),
        )""")
rep("app/routers/api.py", "B4-ingest审计",
    """        db.add(row)
        created += 1
    db.commit()
    return {"created": created, "skipped_dup": skipped}""",
    """        db.add(row)
        created += 1
    db.commit()
    _audit(db, user, "task.ingest", "task", created=created, skipped_dup=skipped)
    return {"created": created, "skipped_dup": skipped}""")

# 8) api.py B4 today 透传
rep("app/routers/api.py", "B4-today透传",
    """        "ai_leader_assigned": r.ai_leader_assigned,
        "ai_blocking_others": r.ai_blocking_others,
        "ai_source_type": r.ai_source_type,""",
    """        "ai_leader_assigned": r.ai_leader_assigned,
        "ai_blocking_others": r.ai_blocking_others,
        "is_meeting": bool(getattr(r, "is_meeting", False)),
        "is_other_request": bool(getattr(r, "is_other_request", False)),
        "is_today_fixed": bool(getattr(r, "is_today_fixed", False)),
        "ai_priority_score": r.ai_priority_score,
        "description": r.description or "",
        "ai_source_type": r.ai_source_type,""")

# 9) api.py B5 feedback 改期 + 审计
rep("app/routers/api.py", "B5-feedback",
    """    if body.get("ai_fixed_start"):
        row.ai_fixed_start = body["ai_fixed_start"]
    db.commit()
    return {"ok": True}""",
    """    if body.get("ai_fixed_start"):
        row.ai_fixed_start = body["ai_fixed_start"]
    if body.get("due_time"):
        row.due_time = str(body["due_time"])[:32]
    db.commit()
    _audit(db, user, "task.feedback", f"task:{task_id}",
           **{k: v for k, v in body.items() if isinstance(v, (str, int, float, bool))})
    return {"ok": True}""")

# 10) api.py B6 早宣入池
rep("app/routers/api.py", "B6-早宣入池",
    '''@router.post("/briefings/morning")
def api_morning(body: dict, user: User = Depends(current_user)):''',
    '''@router.post("/briefings/morning")
def api_morning(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):''')
rep("app/routers/api.py", "B6-早宣入池逻辑",
    """        blockers=body.get("blockers", ""),
    )
    return data


@router.post("/briefings/evening")""",
    """        blockers=body.get("blockers", ""),
    )
    # 手册 1.5「与早宣的关系」：早宣说计划，今日安排帮你把计划排进一天
    # ingest=true 时把口述任务同步拆解入池（与 /tasks/ingest 同一去重逻辑）
    if body.get("ingest") and body.get("tasks_raw", "").strip():
        cap = (
            capture_with_llm(body["tasks_raw"], source="morning_briefing", owner=user.name)
            if body.get("use_llm", True) else
            capture_natural(body["tasks_raw"], source="morning_briefing", owner=user.name)
        )
        data["ingested"] = tasks_ingest({"items": cap.get("candidates", [])}, db=db, user=user)
    _audit(db, user, "briefing.morning", "briefing", ingested=bool(body.get("ingest")))
    return data


@router.post("/briefings/evening")""")

print("修正补丁完成")
