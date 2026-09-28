# -*- coding: utf-8 -*-
"""任务管理智能体 P0 引擎（依据《任务管理智能体落地实施方案 V1.0》）。

职责：任务采集三分类 → 去重合并 → AI 评分排序（B0–B4）→ 今日时间轴排程。
底座：简道云任务数据；入口：V-FLO 智能办公系统首页「今日工作安排」。
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Optional

from ..services.model_gateway import gateway

# 三类任务
TYPE_OVERDUE = "past_unfinished"      # 过去该做未做
TYPE_NEW = "new_input"                # 新输入
TYPE_FIXED = "today_fixed_or_other"   # 今日固定/他人要求

TYPE_LABELS = {
    TYPE_OVERDUE: "过去该做未做",
    TYPE_NEW: "新输入任务",
    TYPE_FIXED: "今日固定/他人要求",
}

# 简道云字段映射（摘自实施方案 3.2，开发前需与管理员核对表单 API 名称）
JDY_FIELD_MAP = {
    "title": "_widget_1668082756215",
    "external_task_no": "_widget_1710402153871",
    "project_code": "_widget_1669429084883",
    "project_name": "_widget_1710399012344",
    "owner": "_widget_1668085072209",
    "collaborators": "_widget_1749021035267",
    "dept": "_widget_1749021035268",
    "status": "_widget_1668690637187",
    "start_time": "_widget_1667894235099",
    "due_time": "_widget_1667894235119",
    "estimated_hours": "_widget_1710399012345",
    "priority": "_widget_1668689007999",
    "description": "_widget_1668085072208",
    "attachments": "_widget_1668085072214",
    "category_l1": "_widget_1749085291625",
    "category_l2": "_widget_1749085291627",
    "task_attr": "_widget_1710399012342",
    "stage": "_widget_1710401489891",
    "wbs_no": "_widget_1710491067381",
    "progress": "_widget_1710492811727",
}

# AI 扩展字段（简道云没有，先存智能体侧；P1 写回）
AI_EXT_FIELDS = [
    "ai_source_type", "ai_urgency", "ai_importance", "ai_value", "ai_impact_scope",
    "ai_complexity", "ai_dependency_ids", "ai_fixed_start", "ai_fixed_end",
    "ai_priority_score", "ai_schedule_block", "ai_remind_policy", "ai_dedup_key",
    "ai_confidence", "ai_user_feedback", "ai_leader_assigned", "ai_blocking_others",
]


def classify_task(t: dict, today: Optional[date] = None) -> str:
    """三类归类（实施方案 4.2）。"""
    today = today or date.today()
    status = (t.get("status") or "").strip()
    due = _parse_date(t.get("due_time") or t.get("due"))
    start = _parse_date(t.get("start_time") or t.get("start"))
    fixed = t.get("ai_fixed_start") or t.get("fixed_time")
    is_meeting = bool(t.get("is_meeting"))
    leader = bool(t.get("ai_leader_assigned"))
    assignee_today = False
    if start and due:
        assignee_today = start <= today <= due
    elif due == today:
        assignee_today = True

    if fixed or is_meeting or leader or t.get("is_other_request") or assignee_today and t.get("is_today_fixed"):
        return TYPE_FIXED
    if due and due < today and status not in ("已完成", "已验收", "done", "completed"):
        return TYPE_OVERDUE
    if t.get("created_today") or t.get("source") in ("mail", "chat", "voice", "upload", "manual", "wecom"):
        return TYPE_NEW
    if due and due <= today and status not in ("已完成", "已验收", "done", "completed"):
        return TYPE_OVERDUE
    return TYPE_NEW


def score_task(t: dict) -> float:
    """PriorityScore（实施方案 4.3.4），0–100 归一。权重可配。"""
    urgency = _urgency_score(t)
    importance = float(t.get("ai_importance") or 3)
    impact = _impact_score(t.get("ai_impact_scope") or "个人")
    effort = max(float(t.get("estimated_hours") or 4), 0.5)
    complexity = max(float(t.get("ai_complexity") or 3), 1)
    blocking = 1.0 if t.get("ai_blocking_others") else 0.0
    leader = 1.0 if t.get("ai_leader_assigned") else 0.0

    score = (
        0.30 * urgency
        + 0.25 * importance
        + 0.15 * impact
        + 0.10 * (5.0 / effort)          # 耗时少优先（归一）
        + 0.10 * (5.0 / complexity)      # 简单优先
        + 0.05 * blocking
        + 0.05 * leader
    )
    # 映射到 0–100
    return round(min(100.0, max(0.0, score * 20.0)), 1)


def assign_bucket(t: dict) -> str:
    """排序桶 B0–B4（实施方案 4.3.3）。"""
    if t.get("ai_fixed_start") or t.get("is_meeting") or t.get("ai_source_type") == TYPE_FIXED:
        return "B0"
    urgency = _urgency_score(t)
    importance = float(t.get("ai_importance") or 3)
    effort = float(t.get("estimated_hours") or 4)
    complexity = float(t.get("ai_complexity") or 3)
    impact = _impact_score(t.get("ai_impact_scope") or "个人")

    important = importance >= 4
    urgent = urgency >= 4
    if important and urgent and effort <= 4 and complexity <= 3:
        return "B1"
    if urgent and important:
        return "B2"
    if important and impact >= 3:
        return "B3"
    return "B4"


def plan_today(
    tasks: list[dict],
    work_minutes: int = 480,
    rest_minutes: int = 60,
    fixed_minutes: int = 120,
    comm_minutes: int = 60,
    buffer_ratio: float = 0.18,
    leader_mode: bool = False,
) -> dict:
    """今日排程：固定锁死 → 桶序插入 → 保留缓冲。"""
    total = work_minutes
    usable = total - rest_minutes - fixed_minutes - comm_minutes
    buffer = int(usable * buffer_ratio)
    available = max(usable - buffer, 0)

    today = date.today()
    enriched = []
    for raw in tasks:
        t = dict(raw)
        t["ai_source_type"] = t.get("ai_source_type") or classify_task(t, today)
        t["ai_priority_score"] = t.get("ai_priority_score") or score_task(t)
        t["bucket"] = assign_bucket(t)
        enriched.append(t)

    fixed_items = sorted(
        [t for t in enriched if t["bucket"] == "B0"],
        key=lambda x: str(x.get("ai_fixed_start") or x.get("start_time") or ""),
    )
    pool = [t for t in enriched if t["bucket"] != "B0"]
    bucket_order = ["B1", "B2", "B3", "B4"]
    if leader_mode:
        # 领导模式：他人任务优先（实施方案 4.3.3）
        pool.sort(key=lambda x: (
            0 if x.get("ai_impact_scope") in ("他人", "部门", "公司", "生产采购") else 1,
            bucket_order.index(x["bucket"]),
            -float(x.get("ai_priority_score") or 0),
        ))
    else:
        pool.sort(key=lambda x: (
            bucket_order.index(x["bucket"]),
            -float(x.get("ai_priority_score") or 0),
        ))

    timeline = []
    used = 0
    for t in fixed_items:
        minutes = _minutes(t)
        timeline.append({
            "type": "fixed", "bucket": "B0", "title": t.get("title"),
            "minutes": minutes, "task": t, "score": t.get("ai_priority_score"),
        })
        used += minutes

    for t in pool:
        minutes = _minutes(t)
        if used + minutes > available and timeline:
            timeline.append({
                "type": "overflow", "bucket": t["bucket"], "title": t.get("title"),
                "minutes": minutes, "task": t, "score": t.get("ai_priority_score"),
                "note": "今日排不下，建议改期或明日优先",
            })
            continue
        timeline.append({
            "type": "scheduled", "bucket": t["bucket"], "title": t.get("title"),
            "minutes": minutes, "task": t, "score": t.get("ai_priority_score"),
        })
        used += minutes

    by_type: dict[str, int] = {}
    for t in enriched:
        k = t["ai_source_type"]
        by_type[k] = by_type.get(k, 0) + 1

    return {
        "date": today.isoformat(),
        "capacity": {
            "total": total, "rest": rest_minutes, "fixed": fixed_minutes,
            "comm": comm_minutes, "buffer": buffer, "available": available,
        },
        "summary": {
            "total_tasks": len(enriched),
            "by_type": {TYPE_LABELS[k]: v for k, v in by_type.items()},
            "scheduled": sum(1 for x in timeline if x["type"] == "scheduled"),
            "overflow": sum(1 for x in timeline if x["type"] == "overflow"),
            "fixed": len(fixed_items),
        },
        "timeline": timeline,
        "leader_mode": leader_mode,
        "tips": [
            "B0 固定事项不可打乱",
            "先做重要+紧急+好干，再做复杂大件",
            "领导模式：先安排他人/部门任务",
            "保留缓冲应对突发",
        ],
    }


def capture_natural(text: str, source: str = "manual", owner: str = "") -> dict:
    """自然语言 → 候选任务（AI 抽取，简版 + 模型增强）。"""
    # 启发式切分：分号/换行/顿号
    import re
    parts = [p.strip() for p in re.split(r"[；;\n]|(?<=[。！？])", text) if p.strip() and len(p.strip()) > 2]
    candidates = []
    for i, p in enumerate(parts[:20]):
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
        })
    return {
        "count": len(candidates),
        "candidates": candidates,
        "hint": "请确认后进入今日任务池；也可用模型增强抽取（generate 提示词）",
    }


def capture_with_llm(text: str, source: str = "manual", owner: str = "") -> dict:
    """用大模型抽取任务（P0 可选，P1 强化）。"""
    prompt = (
        "你是任务采集助理。从下列口语/消息/邮件片段中抽取任务列表。\n"
        "输出 JSON 数组，每项：title, description, due_time(YYYY-MM-DD可空), "
        "estimated_hours(数字), ai_urgency(1-5), ai_importance(1-5), ai_complexity(1-5), "
        "ai_impact_scope(个人/他人/部门/公司/生产采购), ai_leader_assigned(bool)。\n"
        "禁止编造不存在的任务。\n\n输入：\n" + text[:3000]
    )
    result = gateway.chat(
        [{"role": "system", "content": "只输出 JSON，不要解释。"},
         {"role": "user", "content": prompt}],
        model="mimo",
        temperature=0.2,
    )
    import json
    import re
    raw = result.text
    m = re.search(r"\[.*\]", raw, re.S)
    candidates = []
    if m:
        try:
            arr = json.loads(m.group(0))
            for it in arr[:20]:
                if not it.get("title"):
                    continue
                it["source"] = source
                it["owner"] = owner
                it["created_today"] = True
                it["ai_dedup_key"] = _dedup_key(it.get("title", ""))
                candidates.append(it)
        except Exception:  # noqa: BLE001
            pass
    if not candidates:
        return capture_natural(text, source=source, owner=owner)
    return {"count": len(candidates), "candidates": candidates, "mode": "llm"}


def _urgency_score(t: dict) -> float:
    due = _parse_date(t.get("due_time") or t.get("due"))
    today = date.today()
    if not due:
        return float(t.get("ai_urgency") or 3)
    if due < today:
        return 5.0
    delta = (due - today).days
    if delta == 0:
        return 5.0
    if delta <= 1:
        return 4.5
    if delta <= 3:
        return 4.0
    if delta <= 7:
        return 3.0
    return 2.0


def _impact_score(scope: str) -> float:
    order = {"个人": 1, "他人": 2, "部门": 3, "公司": 4, "生产采购": 5}
    return float(order.get(scope, 1))


def _minutes(t: dict) -> int:
    h = t.get("estimated_hours")
    if h:
        return int(max(float(h), 0.25) * 60)
    return 60


def _parse_date(v):
    if not v:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    s = str(v)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _guess_due(text: str) -> Optional[str]:
    import re
    today = date.today()
    if "今天" in text:
        return today.isoformat()
    if "明天" in text:
        return (today + timedelta(days=1)).isoformat()
    if "后天" in text:
        return (today + timedelta(days=2)).isoformat()
    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
            return d.isoformat()
        except ValueError:
            return None
    return None


def _dedup_key(title: str) -> str:
    import re
    return re.sub(r"\s+", "", (title or "").lower())[:64]
