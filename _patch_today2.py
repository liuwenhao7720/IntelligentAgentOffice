# -*- coding: utf-8 -*-
"""_patch_today2.py —— 今日视图过滤与「改期/明日优先」闭环（手册 1.5 三类口径）。

B8 tasks_today：按手册口径过滤今日视图 —— 过去该做未做 + 新输入 + 今日固定/他人要求；
   新增 planned_for 支持：改期到未来的任务今日不再占位，到期日自动回到视图。
B9 feedback：due_time 改期时同步写 ai_schedule_block.planned_for。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
p = ROOT / "app/routers/api.py"
text = p.read_text(encoding="utf-8")

# ---------- B9 feedback 写 planned_for ----------
old_fb = """    if body.get("due_time"):
        row.due_time = str(body["due_time"])[:32]
    db.commit()"""
new_fb = """    if body.get("due_time"):
        row.due_time = str(body["due_time"])[:32]
        sb = dict(row.ai_schedule_block or {})
        sb["planned_for"] = str(body["due_time"])[:10]
        row.ai_schedule_block = sb
    db.commit()"""
if new_fb not in text:
    assert old_fb in text, "B9 锚点未命中"
    text = text.replace(old_fb, new_fb, 1)
    print("  [ok] B9 feedback.planned_for")

# ---------- B8 tasks_today 过滤 ----------
old_today = '''    """首页「今日工作安排」：三分类 + 排序 + 时间轴。"""
    rows = db.execute(select(TaskItem).where(TaskItem.user_id == user.id)).scalars().all()
    tasks = [{'''
new_today = '''    """首页「今日工作安排」：三分类 + 排序 + 时间轴。

    视图口径（手册 1.5）：过去该做未做 + 新输入 + 今日固定/他人要求；
    改期到未来（ai_schedule_block.planned_for > 今天）的任务今日不占容量，到期日自动回到视图。
    """
    from datetime import date as _date, timedelta as _td
    _today = _date.today()
    _tomorrow = (_today + _td(days=1)).isoformat()
    rows = db.execute(select(TaskItem).where(TaskItem.user_id == user.id)).scalars().all()

    def _in_today_view(r: TaskItem) -> bool:
        if r.status in ("已完成", "已验收"):
            return False
        sb = r.ai_schedule_block if isinstance(r.ai_schedule_block, dict) else {}
        planned_for = str(sb.get("planned_for") or "")[:10]
        if planned_for > _today.isoformat():
            return False  # 已改期到未来
        due = (r.due_time or "")[:10]
        fixed = bool(
            r.ai_fixed_start or getattr(r, "is_meeting", False)
            or getattr(r, "is_today_fixed", False) or r.ai_leader_assigned
            or getattr(r, "is_other_request", False)
        )
        created_recent = bool(r.created_at) and (_today - r.created_at.date()).days <= 1
        if fixed:
            return True
        if due:
            return due <= _tomorrow  # 逾期/今日/明日到期
        return created_recent       # 无日期任务仅新输入可见

    rows = [r for r in rows if _in_today_view(r)]
    tasks = [{'''
if new_today not in text:
    assert old_today in text, "B8 锚点未命中"
    text = text.replace(old_today, new_today, 1)
    print("  [ok] B8 tasks_today 视图过滤")

# tasks_today 原有过滤行改为恒真（过滤已前置）
old_filter = '''    } for r in rows if r.status not in ("已完成", "已验收")]'''
new_filter = '''    } for r in rows]'''
if new_filter not in text:
    assert old_filter in text, "B8b 锚点未命中"
    text = text.replace(old_filter, new_filter, 1)
    print("  [ok] B8b 移除旧过滤")

p.write_text(text, encoding="utf-8")
print("补丁2完成")
