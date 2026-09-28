# -*- coding: utf-8 -*-
"""注册早宣/晚总/周计划/周总结/结项自动化 API。"""
from pathlib import Path

ROOT = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")
p = ROOT / "app" / "routers" / "api.py"
t = p.read_text(encoding="utf-8")

if "/briefings" in t:
    print("already has briefings")
else:
    # imports
    t = t.replace(
        "from ..services.export_control import compliance_prompt_snippet, screen",
        "from ..services.briefing import (\n"
        "    build_evening_review, build_morning_plan, build_project_closure,\n"
        "    build_weekly_plan, build_weekly_summary, push_to_jdy,\n"
        ")\n"
        "from ..services.export_control import compliance_prompt_snippet, screen\n"
        "from ..services.jdy import jdy",
    )
    t = t.rstrip() + '''

# ---------- 简道云必做动作自动化：早宣/晚总/周计划/周总结/结项 ----------
@router.post("/briefings/morning")
def api_morning(body: dict, user: User = Depends(current_user)):
    data = build_morning_plan(
        name=user.name,
        dept=user.department,
        tasks_raw=body.get("tasks_raw", ""),
        focus=body.get("focus", ""),
        blockers=body.get("blockers", ""),
    )
    _audit(db=None, user=user, action="briefing.morning", resource="briefing") if False else None
    return data


@router.post("/briefings/evening")
def api_evening(body: dict, user: User = Depends(current_user)):
    return build_evening_review(
        name=user.name,
        dept=user.department,
        done_raw=body.get("done_raw", ""),
        issues_raw=body.get("issues_raw", ""),
        tomorrow=body.get("tomorrow", ""),
    )


@router.post("/briefings/weekly-plan")
def api_weekly_plan(body: dict, user: User = Depends(current_user)):
    return build_weekly_plan(
        name=user.name,
        dept=user.department,
        goals_raw=body.get("goals_raw", ""),
        projects_raw=body.get("projects_raw", ""),
    )


@router.post("/briefings/weekly-summary")
def api_weekly_summary(body: dict, user: User = Depends(current_user)):
    return build_weekly_summary(
        name=user.name,
        dept=user.department,
        done_raw=body.get("done_raw", ""),
        issues_raw=body.get("issues_raw", ""),
    )


@router.post("/briefings/project-closure")
def api_project_closure(body: dict, user: User = Depends(current_user)):
    return build_project_closure(
        project=body.get("project", ""),
        owner=user.name,
        overview=body.get("overview", ""),
        results_raw=body.get("results_raw", ""),
        issues_raw=body.get("issues_raw", ""),
        lessons_raw=body.get("lessons_raw", ""),
    )


@router.post("/briefings/push")
def api_push_jdy(body: dict, user: User = Depends(current_user)):
    """人工确认后推送简道云。body: {payload, kind=task|knowledge}"""
    payload = body.get("payload") or {}
    kind = body.get("kind", "task")
    if not payload:
        raise HTTPException(422, "缺少 payload")
    result = push_to_jdy(payload, kind=kind)
    return result


@router.get("/briefings/jdy-status")
def jdy_status(user: User = Depends(current_user)):
    return {
        "mode": "mock" if jdy.mock else "live",
        "entry_task": jdy.entry_id_task or "(未配置)",
        "entry_knowledge": jdy.entry_id_knowledge or "(未配置)",
        "hint": "配置 JDY_APP_ID / JDY_API_KEY 后自动切 live；当前可演示与联调",
    }
'''
    p.write_text(t, encoding="utf-8")
    print("api ok")
