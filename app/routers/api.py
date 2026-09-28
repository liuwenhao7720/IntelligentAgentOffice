# -*- coding: utf-8 -*-
"""T05/T10 路由：登录、场景卡、会话工作台、留痕、知产、管理看板。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user, dev_login_enabled, issue_dev_token, require_admin
from ..database import (
    Asset, AuditLog, ChatSession, EditDiff, SessionMessage, User, get_db,
)
from ..schemas import (
    AssetCreate, AssetOut, DevLoginIn, ExportCheckIn, ExportCheckOut, FinalizeIn,
    GenerateIn, LoginOut, RatingIn, ScenarioDetailOut, ScenarioOut, SessionCreate,
    SessionOut, TaskProjectIn, TaskProjectOut, TaskProjectUpdate, UserOut,
    MatureGenerateIn, ReviewIn,
)
from ..services.briefing import (
    build_evening_review, build_morning_plan, build_project_closure,
    build_weekly_plan, build_weekly_summary, push_to_jdy,
)
from ..services.export_control import compliance_prompt_snippet, screen
from ..services.task_agent import (
    AI_EXT_FIELDS, JDY_FIELD_MAP, capture_natural, capture_with_llm,
    classify_task, plan_today, score_task,
)
from ..services.mature_rules import ReviewDecision, apply_review, generate_with_review, seed_mature_rules
from ..services.jdy import jdy
from ..services.model_gateway import gateway
from ..services.prompt_builder import build_messages, diff_stats, validate_variables
from ..database import ExportCheck, Scenario, TaskItem, TaskProject

router = APIRouter()


def _audit(db: Session, user: User, action: str, resource: str = "", **detail):
    db.add(AuditLog(user_id=user.id, action=action, resource=resource, detail=detail))
    db.commit()


# ---------- 登录 ----------
@router.post("/auth/dev-login", response_model=LoginOut)
def dev_login(body: DevLoginIn, db: Session = Depends(get_db)):
    if not dev_login_enabled():
        raise HTTPException(403, "开发登录已关闭，请使用企业微信 OAuth")
    user = db.execute(
        select(User).where(User.wecom_userid == f"dev_{body.name}_{body.department}")
    ).scalar_one_or_none()
    if not user:
        user = User(
            wecom_userid=f"dev_{body.name}_{body.department}",
            name=body.name,
            department=body.department,
            position=body.position,
            role=body.role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    token = issue_dev_token(user.id)
    _audit(db, user, "login", "user", mode="dev")
    return LoginOut(token=token, user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


# ---------- 模型 ----------
@router.get("/models")
def list_models(user: User = Depends(current_user)):
    return {"models": gateway.available_models()}


# ---------- 场景卡 ----------
@router.get("/scenarios", response_model=list[ScenarioOut])
def list_scenarios(
    department: str = "",
    category: str = "",
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    stmt = select(Scenario).where(Scenario.status == "active")
    if department:
        stmt = stmt.where(Scenario.department == department)
    if category:
        stmt = stmt.where(Scenario.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Scenario.title.like(like) | Scenario.code.like(like))
    rows = db.execute(stmt.order_by(Scenario.department, Scenario.code)).scalars().all()
    return rows


@router.get("/scenarios/{scenario_id}", response_model=ScenarioDetailOut)
def get_scenario(scenario_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(404, "场景不存在")
    return sc


@router.get("/scenarios/meta/departments")
def departments(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(Scenario.department, func.count()).group_by(Scenario.department)).all()
    return [{"department": d, "count": c} for d, c in rows]


# ---------- 会话工作台 ----------
@router.post("/sessions", response_model=SessionOut)
def create_session(body: SessionCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    scenario = None
    if body.scenario_id:
        scenario = db.get(Scenario, body.scenario_id)
        if not scenario:
            raise HTTPException(404, "场景不存在")
    title = body.title or (scenario.title if scenario else "自由对话")
    session = ChatSession(
        user_id=user.id,
        scenario_id=body.scenario_id,
        title=title,
        model=body.model or (scenario.default_model if scenario else "mimo"),
        variables=body.variables or {},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    _audit(db, user, "session.create", f"session:{session.id}", scenario=body.scenario_id)
    return session


@router.get("/sessions", response_model=list[SessionOut])
def my_sessions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(
        select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.updated_at.desc())
    ).scalars().all()
    return rows


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = db.get(ChatSession, session_id)
    if not s or (s.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "会话不存在")
    return s


@router.post("/sessions/{session_id}/generate")
def generate(
    session_id: int,
    body: GenerateIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    s = db.get(ChatSession, session_id)
    if not s or (s.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "会话不存在")

    # 前端可回写最新填空
    if body.variables:
        merged = dict(s.variables or {})
        merged.update({k: v for k, v in body.variables.items() if v is not None})
        s.variables = merged

    scenario = db.get(Scenario, s.scenario_id) if s.scenario_id else None
    if scenario:
        missing = validate_variables(scenario.variables or [], s.variables or {})
        if missing:
            raise HTTPException(
                422,
                {
                    "message": "缺少必填变量，请补全填空",
                    "missing": [{"key": m.key, "label": m.label} for m in missing],
                },
            )
        template = scenario.prompt_template
        # 出口管制敏感场景强制注入合规约束
        if getattr(scenario, "security_level", "normal") == "export_control":
            template = template + compliance_prompt_snippet()
        model = body.model or s.model or scenario.default_model
    else:
        template = (
            "你是 V-FLO 集团智能办公助理，用中文专业、简洁地协助员工完成工作。\n"
            "要求：结论先行；涉及日期、金额、人名必须准确，不确定时明确指出；输出结构化内容。"
        )
        model = body.model or s.model or "mimo"

    history = [{"role": m.role, "content": m.content} for m in s.messages if m.role in ("user", "assistant")]
    messages = build_messages(template, s.variables or {}, body.extra_instructions, history)

    result = gateway.chat(messages, model=model)

    # 保存 user 触发说明（如有）与 assistant 初稿
    if body.extra_instructions:
        db.add(SessionMessage(session_id=s.id, role="user", content=body.extra_instructions))
    db.add(
        SessionMessage(
            session_id=s.id,
            role="assistant",
            content=result.text,
            model=f"{result.provider}:{result.model}",
            is_final=False,
        )
    )
    s.model = model
    s.tokens_in += result.tokens_in
    s.tokens_out += result.tokens_out
    if scenario:
        scenario.use_count += 1
    db.commit()
    db.refresh(s)
    _audit(db, user, "session.generate", f"session:{s.id}", model=model, degraded=result.degraded)
    return {
        "session_id": s.id,
        "model": result.model,
        "provider": result.provider,
        "degraded": result.degraded,
        "text": result.text,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
    }


@router.post("/sessions/{session_id}/finalize")
def finalize(
    session_id: int,
    body: FinalizeIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """保存人工定稿，并记录 AI→定稿 diff（数字资产）。"""
    s = db.get(ChatSession, session_id)
    if not s or (s.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "会话不存在")
    ai_msg = next((m for m in reversed(s.messages) if m.role == "assistant"), None)
    ai_text = ai_msg.content if ai_msg else ""
    summary, ratio = diff_stats(ai_text, body.content)

    db.add(EditDiff(
        session_id=s.id,
        field="content",
        ai_text=ai_text,
        final_text=body.content,
        diff_summary=summary,
        edit_ratio=ratio,
    ))
    db.add(SessionMessage(
        session_id=s.id,
        role="assistant",
        content=body.content,
        model="human-final",
        is_final=True,
    ))
    s.status = "done"
    db.commit()
    _audit(db, user, "session.finalize", f"session:{s.id}", edit_ratio=ratio)
    return {"ok": True, "diff_summary": summary, "edit_ratio": ratio}


@router.post("/sessions/{session_id}/rating")
def rate(session_id: int, body: RatingIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = db.get(ChatSession, session_id)
    if not s or (s.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "会话不存在")
    s.rating = body.rating
    db.commit()
    return {"ok": True}


# ---------- 知产库 ----------
@router.post("/assets", response_model=AssetOut)
def create_asset(body: AssetCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    asset = Asset(
        session_id=body.session_id,
        user_id=user.id,
        title=body.title,
        content=body.content,
        department=user.department,
        visibility=body.visibility,
        tags=body.tags,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    _audit(db, user, "asset.create", f"asset:{asset.id}")
    return asset


@router.get("/assets", response_model=list[AssetOut])
def list_assets(
    scope: str = "all",  # mine / dept / company / all
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    stmt = select(Asset)
    if scope == "mine":
        stmt = stmt.where(Asset.user_id == user.id)
    elif scope == "dept":
        stmt = stmt.where(Asset.department == user.department, Asset.visibility.in_(["dept", "company"]))
    elif scope == "company":
        stmt = stmt.where(Asset.visibility == "company")
    else:
        stmt = stmt.where(
            (Asset.user_id == user.id)
            | (Asset.visibility == "company")
            | ((Asset.visibility == "dept") & (Asset.department == user.department))
        )
    if q:
        stmt = stmt.where(Asset.title.like(f"%{q}%") | Asset.content.like(f"%{q}%"))
    rows = db.execute(stmt.order_by(Asset.created_at.desc()).limit(200)).scalars().all()
    return rows


@router.post("/assets/{asset_id}/feature")
def feature_asset(asset_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    a = db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "资产不存在")
    a.featured = not a.featured
    if a.featured:
        a.visibility = "company"
    db.commit()
    return {"ok": True, "featured": a.featured}


# ---------- 管理看板 ----------
@router.get("/admin/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    total_users = db.execute(select(func.count()).select_from(User)).scalar() or 0
    total_sessions = db.execute(select(func.count()).select_from(ChatSession)).scalar() or 0
    total_assets = db.execute(select(func.count()).select_from(Asset)).scalar() or 0
    tokens_in = db.execute(select(func.coalesce(func.sum(ChatSession.tokens_in), 0))).scalar() or 0
    tokens_out = db.execute(select(func.coalesce(func.sum(ChatSession.tokens_out), 0))).scalar() or 0

    top_scenarios = db.execute(
        select(Scenario.title, Scenario.use_count, Scenario.department)
        .where(Scenario.status == "active")
        .order_by(Scenario.use_count.desc())
        .limit(10)
    ).all()

    dept_usage = db.execute(
        select(User.department, func.count(ChatSession.id))
        .join(ChatSession, ChatSession.user_id == User.id)
        .group_by(User.department)
    ).all()

    avg_edit = db.execute(select(func.coalesce(func.avg(EditDiff.edit_ratio), 0))).scalar() or 0

    return {
        "total_users": total_users,
        "total_sessions": total_sessions,
        "total_assets": total_assets,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "avg_edit_ratio": round(float(avg_edit), 3),
        "top_scenarios": [
            {"title": t, "use_count": u, "department": d} for t, u, d in top_scenarios
        ],
        "dept_usage": [{"department": d, "sessions": c} for d, c in dept_usage],
    }


# ---------- 出口管制合规 ----------
@router.post("/export-checks", response_model=ExportCheckOut)
def create_export_check(body: ExportCheckIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    result = screen(
        customer_name=body.customer_name,
        country=body.country,
        end_user=body.end_user,
        end_use=body.end_use,
        product_desc=body.product_desc,
        hs_code=body.hs_code,
        extra_red_flags=body.extra_red_flags,
    )
    from datetime import datetime as _dt
    import uuid as _uuid
    case_no = "EXP" + _dt.utcnow().strftime("%Y%m%d%H%M%S") + _uuid.uuid4().hex[:4].upper()
    row = ExportCheck(
        case_no=case_no,
        user_id=user.id,
        customer_name=body.customer_name,
        country=body.country,
        end_user=body.end_user,
        end_use=body.end_use,
        product_desc=body.product_desc,
        hs_code=body.hs_code,
        country_risk=result.country_risk,
        sanctions_hit=result.sanctions_hit,
        item_control=result.item_control,
        license_needed=result.license_needed,
        red_flags=result.red_flags,
        decision=result.decision,
        decision_note=result.decision_note,
        checklist=result.checklist,
        status="submitted",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(db, user, "export_check.create", f"export:{row.case_no}", decision=result.decision)
    return row


@router.get("/export-checks", response_model=list[ExportCheckOut])
def list_export_checks(db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(ExportCheck)
    if user.role != "admin":
        stmt = stmt.where(ExportCheck.user_id == user.id)
    return db.execute(stmt.order_by(ExportCheck.created_at.desc()).limit(100)).scalars().all()


@router.get("/export-checks/{case_no}", response_model=ExportCheckOut)
def get_export_check(case_no: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.execute(select(ExportCheck).where(ExportCheck.case_no == case_no)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "审查单不存在")
    if row.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "无权查看")
    return row


@router.get("/compliance/prompt-snippet")
def compliance_snippet(user: User = Depends(current_user)):
    return {"snippet": compliance_prompt_snippet()}


@router.get("/admin/kpi-scenario-map")
def kpi_scenario_map(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = db.execute(select(Scenario).where(Scenario.status == "active")).scalars().all()
    out = []
    for s in rows:
        for k in (s.kpi_links or []):
            item = {"scenario": s.title, "code": s.code, "department": s.department}
            item.update(k or {})
            out.append(item)
    return out

# ---------- 任务项目（资料文件夹 → Mimo项目 → 工作流） ----------
@router.post("/task-projects", response_model=TaskProjectOut)
def create_task_project(body: TaskProjectIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from datetime import datetime as _dt
    import uuid as _uuid
    code = "TP" + _dt.utcnow().strftime("%Y%m%d") + _uuid.uuid4().hex[:4].upper()
    folder_name = body.folder_name
    if not folder_name and body.folder_path:
        folder_name = body.folder_path.replace("\\", "/").rstrip("/").split("/")[-1]
    row = TaskProject(
        code=code,
        user_id=user.id,
        name=body.name,
        department=body.department or user.department,
        position=body.position or user.position,
        folder_path=body.folder_path,
        folder_name=folder_name or "",
        materials=body.materials or [],
        scenario_id=body.scenario_id,
        status="materials_ready" if (body.folder_path or body.materials) else "created",
        progress=[{"step": "1-创建任务项目", "status": "done", "note": "登记资料文件夹"}],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit(db, user, "task_project.create", f"tp:{row.code}")
    return row


@router.get("/task-projects", response_model=list[TaskProjectOut])
def list_task_projects(db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(TaskProject).where(TaskProject.user_id == user.id).order_by(TaskProject.updated_at.desc())
    return db.execute(stmt.limit(100)).scalars().all()


@router.get("/task-projects/{code}", response_model=TaskProjectOut)
def get_task_project(code: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.execute(select(TaskProject).where(TaskProject.code == code)).scalar_one_or_none()
    if not row or (row.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "任务项目不存在")
    return row


@router.patch("/task-projects/{code}", response_model=TaskProjectOut)
def update_task_project(code: str, body: TaskProjectUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.execute(select(TaskProject).where(TaskProject.code == code)).scalar_one_or_none()
    if not row or (row.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "任务项目不存在")
    if body.materials is not None:
        row.materials = body.materials
    if body.mimo_project is not None:
        row.mimo_project = body.mimo_project
        row.mimo_ready = 1
        if row.status in ("created", "materials_ready"):
            row.status = "mimo_ready"
        row.progress = list(row.progress or []) + [{
            "step": "2-绑定Mimo项目", "status": "done",
            "note": "Mimo项目：" + str(body.mimo_project),
        }]
    if body.scenario_id is not None:
        row.scenario_id = body.scenario_id
    if body.workflow_stage is not None:
        row.workflow_stage = body.workflow_stage
    if body.progress_note:
        row.progress = list(row.progress or []) + [{
            "step": "3-工作流推进", "status": "doing", "note": body.progress_note,
        }]
        if row.status == "mimo_ready":
            row.status = "running"
    if body.output:
        row.outputs = list(row.outputs or []) + [body.output]
    if body.status is not None:
        row.status = body.status
    db.commit()
    db.refresh(row)
    _audit(db, user, "task_project.update", f"tp:{row.code}", status=row.status)
    return row


@router.post("/task-projects/{code}/sessions", response_model=SessionOut)
def session_for_project(code: str, body: SessionCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """在任务项目下开场景会话（Mimo 项目建立后的下一步）。"""
    row = db.execute(select(TaskProject).where(TaskProject.code == code)).scalar_one_or_none()
    if not row or (row.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "任务项目不存在")
    if not row.mimo_ready:
        raise HTTPException(422, "请先在 Mimo V2.6 新建项目并绑定，再开启工作流")
    scenario = db.get(Scenario, body.scenario_id) if body.scenario_id else None
    session = ChatSession(
        user_id=user.id,
        scenario_id=body.scenario_id,
        title="[%s] %s" % (row.code, body.title or (scenario.title if scenario else "任务会话")),
        model=body.model or (scenario.default_model if scenario else "mimo"),
        variables=body.variables or {},
    )
    db.add(session)
    row.status = "running"
    row.progress = list(row.progress or []) + [{
        "step": "3-场景工作流", "status": "doing",
        "note": "启动：" + (scenario.title if scenario else "自由会话"),
    }]
    db.commit()
    db.refresh(session)
    return session

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

# ---------- 成熟规则：自动成稿 → 人工审核放行 ----------
@router.post("/mature-rules/seed")
def api_seed_mature(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    n = seed_mature_rules(db)
    return {"created_or_updated": n}


@router.get("/mature-rules")
def list_mature_rules(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(Scenario).where(Scenario.maturity.in_(["production", "validated"]))).scalars().all()
    return [{
        "id": s.id, "code": s.code, "title": s.title, "department": s.department,
        "maturity": getattr(s, "maturity", "draft"), "roles": s.roles, "timing": s.timing,
        "default_model": s.default_model, "usage_steps": getattr(s, "usage_steps", ""),
    } for s in rows]


@router.post("/mature-rules/{code}/generate")
def mature_generate(code: str, body: MatureGenerateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sc = db.execute(select(Scenario).where(Scenario.code == code)).scalar_one_or_none()
    if not sc:
        raise HTTPException(404, "规则不存在")
    from ..services.prompt_builder import validate_variables
    missing = validate_variables(sc.variables or [], body.variables or {})
    if missing:
        raise HTTPException(422, {
            "message": "缺少必填变量",
            "missing": [{"key": m.key, "label": m.label} for m in missing],
        })
    return generate_with_review(db, user, sc, body.variables or {}, model=body.model)


@router.post("/mature-rules/review/{session_id}")
def mature_review(session_id: int, body: ReviewIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.action not in ("approve", "revise", "reject"):
        raise HTTPException(422, "action 必须是 approve/revise/reject")
    try:
        return apply_review(db, user, session_id, ReviewDecision(action=body.action, note=body.note), final_text=body.final_text)
    except ValueError as e:
        raise HTTPException(404, str(e))

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
