# -*- coding: utf-8 -*-
"""T05/T10 路由：登录、场景卡、会话工作台、留痕、知产、管理看板。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import current_user, dev_login_enabled, issue_dev_token, require_admin, require_perm
from ..config import get_settings
from ..database import (
    Asset, AuditLog, Briefing, ChatSession, EditDiff, SessionMessage, User, get_db,
)
from ..schemas import (
    AssetCreate, AssetOut, DevLoginIn, ExportCheckIn, ExportCheckOut, FinalizeIn,
    GenerateIn, LoginOut, RatingIn, ScenarioDetailOut, ScenarioOut, SessionCreate,
    SessionOut, TaskProjectIn, TaskProjectOut, TaskProjectUpdate, UserOut,
    MatureGenerateIn, ReviewIn, ExportReviewIn, BriefingOut, UserAdminOut, UserPatchIn,
)
from ..services.briefing import (
    build_evening_review, build_morning_plan, build_project_closure,
    build_weekly_plan, build_weekly_summary, push_to_jdy,
)
from ..services.export_control import compliance_prompt_snippet, screen
from ..services.task_agent import (
    AI_EXT_FIELDS, JDY_FIELD_MAP, capture_natural, capture_with_llm,
    classify_task, jdy_row_to_task, plan_today, score_task,
)
from ..services.mature_rules import (
    ReviewDecision, ReviewForbidden, apply_review, generate_with_review, seed_mature_rules,
)
from ..services.jdy import jdy
from ..services.model_gateway import gateway
from ..services.prompt_builder import build_messages, diff_stats, validate_variables
from ..services.sensitive_scan import scan_text, scan_variables
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

    # 输入规范化（schemas 已做长度/取值校验）
    name = body.name.strip()
    department = body.department.strip()
    position = body.position.strip()
    if not name:
        raise HTTPException(422, "姓名不能为空")
    wecom_userid = f"dev_{name}_{department}"

    # 越权防护：role=admin 仅对 DEV_ADMIN_USERS 白名单（姓名或 dev_姓名_部门）生效，
    # 其余一律 staff；老用户角色以数据库为准，登录接口绝不升/降权
    admins = {a.strip() for a in get_settings().dev_admin_users.split(",") if a.strip()}
    want_admin = body.role == "admin" and (name in admins or wecom_userid in admins)

    user = db.execute(
        select(User).where(User.wecom_userid == wecom_userid)
    ).scalar_one_or_none()
    if not user:
        user = User(
            wecom_userid=wecom_userid,
            name=name,
            department=department,
            position=position,
            role="admin" if want_admin else "staff",
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # 并发首次登录同一用户：另一请求已抢先插入，回滚后重查（修复 500）
            db.rollback()
            user = db.execute(
                select(User).where(User.wecom_userid == wecom_userid)
            ).scalar_one_or_none()
            if not user:
                raise HTTPException(500, "登录失败，请重试")
        else:
            db.refresh(user)
    else:
        # 老用户登录：同步最新姓名/岗位资料
        changed = False
        if user.name != name or user.position != position:
            user.name = name
            user.position = position
            changed = True
        # 白名单是 admin 授权的唯一入口：在名单内的老用户补授 admin（名单外绝不降权/升权）
        in_whitelist = name in admins or wecom_userid in admins
        if in_whitelist and user.role != "admin":
            user.role = "admin"
            changed = True
        if changed:
            db.commit()

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


@router.post("/scenarios/{scenario_id}/extract-vars")
def extract_vars(scenario_id: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """智能填参：把用户"说人话"的一段描述映射为场景卡填空变量。

    前端工作台默认只展示一个大输入框；生成前调用本接口自动识别参数，
    识别不到的必填项再由用户补填（保留缺关键变量禁止生成的门禁）。
    """
    sc = db.get(Scenario, scenario_id)
    if not sc:
        raise HTTPException(404, "场景不存在")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(422, "请先用一段话描述需求")
    var_defs = sc.variables or []
    if not var_defs:
        return {"variables": {}, "missing": []}

    spec = "\n".join(
        f"- {v.get('key')}（{v.get('label', v.get('key'))}"
        f"{'，必填' if v.get('required', True) else '，选填'}"
        f"{('，示例：' + str(v.get('placeholder'))) if v.get('placeholder') else ''}）"
        for v in var_defs[:30]
    )
    prompt = (
        f"你是参数提取助理。场景「{sc.title}」需要以下参数：\n{spec}\n\n"
        f"从用户描述中提取这些参数，输出 JSON 对象（键为参数名）。\n"
        "规则：描述中没有的信息不要编造、键省略；值要简短忠实于原文。\n\n"
        f"用户描述：\n{text[:3000]}"
    )
    variables: dict = {}
    try:
        result = gateway.chat(
            [{"role": "system", "content": "只输出 JSON 对象，不要解释，不要用 markdown 代码块。"},
             {"role": "user", "content": prompt}],
            model=body.get("model") or "mimo",
            temperature=0.1,
            max_tokens=800,
        )
        import json
        import re
        m = re.search(r"\{.*\}", result.text, re.S)
        if m:
            raw = json.loads(m.group(0))
            valid_keys = {v.get("key") for v in var_defs}
            variables = {k: str(vv).strip() for k, vv in raw.items()
                         if k in valid_keys and str(vv).strip()}
    except Exception:
        variables = {}  # 提取失败不阻断：退回手工补填
    missing = [
        {"key": v.get("key"), "label": v.get("label", v.get("key"))}
        for v in var_defs
        if v.get("required", True) and not variables.get(v.get("key") or "")
    ]
    _audit(db, user, "scenario.extract_vars", f"scenario:{sc.code}", filled=len(variables), missing=len(missing))
    return {"variables": variables, "missing": missing}


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
        privacy=body.privacy or "standard",
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
        locked = False
        # 出口管制/敏感场景：强制注入合规约束 + 锁定指定模型通道
        # （附件3 §2.2「敏感场景…模型选择被锁定」、§3.4「出口相关强制走指定通道」）
        if getattr(scenario, "security_level", "normal") in ("export_control", "sensitive"):
            template = template + compliance_prompt_snippet()
            model = scenario.default_model
            locked = True
        else:
            model = body.model or s.model or scenario.default_model
    else:
        template = (
            "你是 V-FLO 集团智能办公助理，用中文专业、简洁地协助员工完成工作。\n"
            "要求：结论先行；涉及日期、金额、人名必须准确，不确定时明确指出；输出结构化内容。"
        )
        model = body.model or s.model or "mimo"
        locked = False

    # 个人月度额度（附件3 §2.3：可配；超额仅提醒，不锁死）
    quota_exceeded = False
    quota = get_settings().monthly_token_quota
    if quota > 0:
        from datetime import datetime as _dtx
        month_start = _dtx.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = db.execute(
            select(func.coalesce(func.sum(ChatSession.tokens_in + ChatSession.tokens_out), 0))
            .where(ChatSession.user_id == user.id, ChatSession.created_at >= month_start)
        ).scalar() or 0
        quota_exceeded = used >= quota

    history = [{"role": m.role, "content": m.content} for m in s.messages if m.role in ("user", "assistant")]
    messages = build_messages(template, s.variables or {}, body.extra_instructions, history)

    # 附件3 §3.4：提示词与产出过敏感信息扫描，命中标记（不阻断）
    sensitive_hits = scan_variables(s.variables) + scan_text(body.extra_instructions or "")

    result = gateway.chat(messages, model=model)
    sensitive_hits = sorted(set(sensitive_hits + scan_text(result.text)))

    # 附件3 §3.4：「仅元数据留痕」会话不存内容，只留占位（审计轨迹仍保留）
    meta_only = getattr(s, "privacy", "standard") == "metadata_only"
    stored_text = "[仅元数据留痕会话，内容未入库]" if meta_only else result.text

    # 保存 user 触发说明（如有）与 assistant 初稿
    if body.extra_instructions:
        db.add(SessionMessage(session_id=s.id, role="user",
                              content="[仅元数据留痕]" if meta_only else body.extra_instructions))
    db.add(
        SessionMessage(
            session_id=s.id,
            role="assistant",
            content=stored_text,
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
    _audit(db, user, "session.generate", f"session:{s.id}", model=model,
           degraded=result.degraded, quota_exceeded=quota_exceeded,
           sensitive_hits=sensitive_hits, privacy=getattr(s, "privacy", "standard"))
    return {
        "session_id": s.id,
        "model": result.model,
        "provider": result.provider,
        "degraded": result.degraded,
        "model_locked": locked,
        "quota_exceeded": quota_exceeded,
        "text": result.text,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "sensitive_hits": sensitive_hits,
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
    if getattr(s, "privacy", "standard") == "metadata_only":
        raise HTTPException(422, "仅元数据留痕会话不保存内容，无需定稿")
    ai_msg = next((m for m in reversed(s.messages) if m.role == "assistant"), None)
    if not ai_msg:
        raise HTTPException(422, "请先生成初稿，再保存定稿")
    # 成熟规则 production：未审核放行不得定稿归档（附件5 §8.3.3）
    if getattr(s, "review_status", "") == "awaiting_review":
        raise HTTPException(409, "本稿为成熟规则自动成稿，须经理/授权人「审核放行」后才能定稿与归档")
    ai_text = ai_msg.content
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
    _audit(db, user, "session.rating", f"session:{s.id}", rating=body.rating)
    return {"ok": True}


@router.get("/sessions/{session_id}/diffs")
def session_diffs(session_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """AI初稿 vs 人工定稿 diff 查看（附件3 §1.1 知产库「看改动痕迹」/§3.2）。"""
    s = db.get(ChatSession, session_id)
    if not s or (s.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "会话不存在")
    rows = db.execute(
        select(EditDiff).where(EditDiff.session_id == session_id).order_by(EditDiff.created_at)
    ).scalars().all()
    return [{
        "id": d.id, "field": d.field, "diff_summary": d.diff_summary,
        "edit_ratio": d.edit_ratio, "ai_text": d.ai_text, "final_text": d.final_text,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    } for d in rows]


@router.get("/scenarios-market")
def scenarios_market(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """场景卡市场（附件3 §3.3）：使用次数、平均评分、最近改进记录。"""
    rows = db.execute(select(Scenario).where(Scenario.status == "active")).scalars().all()
    ratings = db.execute(
        select(ChatSession.scenario_id, func.avg(ChatSession.rating), func.count(ChatSession.rating))
        .where(ChatSession.rating.isnot(None), ChatSession.scenario_id.isnot(None))
        .group_by(ChatSession.scenario_id)
    ).all()
    rmap = {sid: (round(float(avg), 2), cnt) for sid, avg, cnt in ratings}
    return [{
        "code": s.code, "title": s.title, "department": s.department,
        "use_count": s.use_count or 0,
        "avg_rating": (rmap.get(s.id) or (None, 0))[0],
        "rating_count": (rmap.get(s.id) or (None, 0))[1],
        "version": s.version, "author": s.author,
        "last_change": s.updated_at.isoformat() if s.updated_at else None,
        "maturity": getattr(s, "maturity", "draft"),
    } for s in sorted(rows, key=lambda x: -(x.use_count or 0))]


# ---------- 知产库 ----------
@router.post("/assets", response_model=AssetOut)
def create_asset(body: AssetCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    # 附件5 §1.3 五步法「定稿再归档」、§8.3.3「放行后才能入库」
    if body.session_id:
        s = db.get(ChatSession, body.session_id)
        if s and s.user_id == user.id:
            if getattr(s, "review_status", "") == "awaiting_review":
                raise HTTPException(409, "成熟规则产出须审核放行后才能归档入库")
            if s.status != "done":
                raise HTTPException(422, "请先保存人工定稿，再归档知产库")
    # 附件3 §3.4：入库前敏感信息扫描，命中则打标
    tags = list(body.tags or [])
    hits = scan_text(body.title + "\n" + body.content)
    if hits and "敏感-已标记" not in tags:
        tags.append("敏感-已标记")
    asset = Asset(
        session_id=body.session_id,
        user_id=user.id,
        title=body.title,
        content=body.content,
        department=user.department,
        visibility=body.visibility,
        tags=tags,
        distributed_to=body.distributed_to or [],
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    _audit(db, user, "asset.create", f"asset:{asset.id}",
           visibility=body.visibility, distributed_to=body.distributed_to,
           sensitive_hits=hits)
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
    _audit(db, user, "asset.feature", f"asset:{a.id}", featured=a.featured)
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

    # 场景性价比：每卡 调用次数 × tokens × 平均修改率（附件3 §2.3）
    sc_rows = db.execute(
        select(
            ChatSession.scenario_id,
            func.count(ChatSession.id),
            func.coalesce(func.sum(ChatSession.tokens_in + ChatSession.tokens_out), 0),
        ).where(ChatSession.scenario_id.isnot(None))
        .group_by(ChatSession.scenario_id)
    ).all()
    sc_map = {sid: (cnt, int(tok)) for sid, cnt, tok in sc_rows}
    sc_titles = {s.id: s.title for s in db.execute(
        select(Scenario).where(Scenario.id.in_(list(sc_map.keys()) or [0]))).scalars().all()}
    scenario_costs = [
        {"scenario_id": sid, "title": sc_titles.get(sid, f"#{sid}"),
         "sessions": cnt, "tokens": tok}
        for sid, (cnt, tok) in sorted(sc_map.items(), key=lambda kv: -kv[1][1])[:20]
    ]

    return {
        "scenario_costs": scenario_costs,
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
        middleman=body.middleman,
        arrival_country=body.arrival_country,
        end_user_country=body.end_user_country,
    )
    from datetime import datetime as _dt
    import uuid as _uuid
    case_no = "EXP" + _dt.utcnow().strftime("%Y%m%d%H%M%S") + _uuid.uuid4().hex[:4].upper()
    row = ExportCheck(
        case_no=case_no,
        user_id=user.id,
        customer_name=body.customer_name,
        middleman=body.middleman,
        arrival_country=body.arrival_country,
        end_user_country=body.end_user_country,
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


@router.post("/export-checks/{case_no}/review", response_model=ExportCheckOut)
def review_export_check(case_no: str, body: ExportReviewIn,
                        db: Session = Depends(get_db),
                        user: User = Depends(require_perm("export.review"))):
    """合规官终审（附件1 §2.4「合规官终审」/§2.1 G5 审批记录 / WBS T20）。

    - 仅 compliance（合规官）/ admin 可审批；提交人不能审批自己的审查单；
    - 审批结论与签字落库（reviewed_by/reviewed_at/review_note），审查单不可删改；
    - decision_override 可覆盖系统初筛结论（系统只初筛，人终审）。
    """
    row = db.execute(select(ExportCheck).where(ExportCheck.case_no == case_no)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "审查单不存在")
    if row.user_id == user.id:
        raise HTTPException(403, "提交人不能审批自己的审查单，须由合规官终审")
    row.reviewed_by = user.name
    row.reviewed_at = datetime.utcnow()
    row.review_note = body.note
    if body.action == "approve":
        row.status = "approved"
        row.decision = body.decision_override or "pass"
    elif body.action == "reject":
        row.status = "rejected"
        row.decision = "reject"
    else:  # conditions
        row.status = "approved"
        row.decision = body.decision_override or "manual_review"
        if body.note:
            row.decision_note = (row.decision_note or "") + f" 【放行条件】{body.note}"
    db.commit()
    db.refresh(row)
    _audit(db, user, "export_check.review", f"export:{case_no}",
           review_action=body.action, decision=row.decision)
    return row


@router.get("/compliance/prompt-snippet")
def compliance_snippet(user: User = Depends(current_user)):
    return {"snippet": compliance_prompt_snippet()}


@router.get("/admin/diff-insights")
def diff_insights(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """diff 提炼（附件3 §3.2）：聚合人改 AI 的高频新增/删除行，生成提示词改进建议线索。"""
    rows = db.execute(select(EditDiff).order_by(EditDiff.created_at.desc()).limit(500)).scalars().all()
    from collections import Counter
    added = Counter()
    removed = Counter()
    for d in rows:
        for part in (d.diff_summary or "").split(" | "):
            if part.startswith("新增："):
                for line in part[3:].split("；"):
                    line = line.strip().rstrip("…")
                    if len(line) >= 4:
                        added[line[:60]] += 1
            elif part.startswith("删除/改写："):
                for line in part[5:].split("；"):
                    line = line.strip().rstrip("…")
                    if len(line) >= 4:
                        removed[line[:60]] += 1
    return {
        "total_diffs": len(rows),
        "avg_edit_ratio": round(sum(d.edit_ratio for d in rows) / len(rows), 3) if rows else 0,
        "top_added": [{"line": k, "count": v} for k, v in added.most_common(10)],
        "top_removed": [{"line": k, "count": v} for k, v in removed.most_common(10)],
        "hint": "高频新增行 = 模板缺的内容；高频删除行 = 模板多写的内容。据此修订场景卡提示词并升版。",
    }


@router.get("/admin/kpi-sources")
def kpi_sources(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """列出全部场景卡 KPI 挂接的简道云数据来源（T18 取数目录）。"""
    rows = db.execute(select(Scenario).where(Scenario.status == "active")).scalars().all()
    sources = {}
    for s in rows:
        for k in (s.kpi_links or []):
            src = (k or {}).get("source") or ""
            if not src:
                continue
            item = sources.setdefault(src, {"source": src, "kpis": set(), "scenarios": set()})
            item["kpis"].add(k.get("name", ""))
            item["scenarios"].add(s.code)
    return [{"source": v["source"], "kpis": sorted(v["kpis"]),
             "scenarios": sorted(v["scenarios"])} for v in sources.values()]


@router.post("/admin/kpi-fetch")
def kpi_fetch(body: dict, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """简道云 KPI 取数对接（附件1 WBS T18）。

    body: {"entry_id": "...", "filter": {...可选...}, "sample_fields": [...可选...]}
    返回该表单的数据条数与样例行（默认取已配置的任务管理/知识库表单）。
    MOCK 模式下返回提示而非数据。
    """
    entry_id = (body.get("entry_id") or "").strip()
    if not entry_id:
        entry_id = jdy.entry_id_task or jdy.entry_id_knowledge
    if not entry_id:
        raise HTTPException(422, "未配置任何简道云表单入口（JDY_ENTRY_TASK/JDY_ENTRY_KNOWLEDGE）")
    if jdy.mock:
        return {"mode": "mock", "entry_id": entry_id, "count": 0, "sample": [],
                "hint": "JDY 为 MOCK 模式：配置 JDY_APP_ID/JDY_API_KEY 后返回真实取数"}
    flt = body.get("filter") if isinstance(body.get("filter"), dict) else None
    rows = jdy.query_form(entry_id, filter=flt, limit=min(int(body.get("limit") or 100), 100))
    sample_fields = body.get("sample_fields") or []
    sample = []
    for r in rows[: int(body.get("sample") or 5)]:
        if sample_fields:
            sample.append({k: r.get(k) for k in sample_fields})
        else:
            sample.append({"_id": r.get("_id"), **{k: v for i, (k, v) in enumerate(r.items()) if i < 8}})
    return {"mode": "live", "entry_id": entry_id, "count": len(rows), "sample": sample}


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
def _require_text(body: dict, key: str, label: str) -> str:
    v = (body.get(key) or "").strip()
    if not v:
        raise HTTPException(422, f"请先口述{label}（{key} 不能为空）")
    if len(v) > 5000:
        raise HTTPException(422, f"{label}内容过长（≤5000 字）")
    return v


def _save_briefing(db: Session, user: User, data: dict) -> Briefing:
    row = Briefing(
        user_id=user.id,
        department=user.department,
        kind=data.get("type", ""),
        title=data.get("title", "")[:250],
        content=data.get("content", ""),
        wecom_card=data.get("wecom_card", ""),
        jdy_payload=data.get("jdy_payload") or {},
        jdy_tasks=data.get("jdy_tasks") or [],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    data["briefing_id"] = row.id
    return row


@router.post("/briefings/morning")
def api_morning(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    tasks_raw = _require_text(body, "tasks_raw", "今日任务")
    data = build_morning_plan(
        name=user.name,
        dept=user.department,
        tasks_raw=tasks_raw,
        focus=body.get("focus", "")[:1000],
        blockers=body.get("blockers", "")[:1000],
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
    _save_briefing(db, user, data)
    _audit(db, user, "briefing.morning", f"briefing:{data['briefing_id']}", ingested=bool(body.get("ingest")))
    return data


@router.post("/briefings/evening")
def api_evening(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = build_evening_review(
        name=user.name,
        dept=user.department,
        done_raw=_require_text(body, "done_raw", "今日完成情况"),
        issues_raw=body.get("issues_raw", "")[:2000],
        tomorrow=body.get("tomorrow", "")[:2000],
    )
    _save_briefing(db, user, data)
    _audit(db, user, "briefing.evening", f"briefing:{data['briefing_id']}")
    return data


@router.post("/briefings/weekly-plan")
def api_weekly_plan(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = build_weekly_plan(
        name=user.name,
        dept=user.department,
        goals_raw=_require_text(body, "goals_raw", "本周目标"),
        projects_raw=body.get("projects_raw", "")[:2000],
    )
    _save_briefing(db, user, data)
    _audit(db, user, "briefing.weekly_plan", f"briefing:{data['briefing_id']}")
    return data


@router.post("/briefings/weekly-summary")
def api_weekly_summary(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = build_weekly_summary(
        name=user.name,
        dept=user.department,
        done_raw=_require_text(body, "done_raw", "本周完成"),
        issues_raw=body.get("issues_raw", "")[:2000],
    )
    _save_briefing(db, user, data)
    _audit(db, user, "briefing.weekly_summary", f"briefing:{data['briefing_id']}")
    return data


@router.post("/briefings/project-closure")
def api_project_closure(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = (body.get("project") or "").strip()
    if not project:
        raise HTTPException(422, "请填写项目名称（project 不能为空）")
    data = build_project_closure(
        project=project[:128],
        owner=user.name,
        overview=_require_text(body, "overview", "项目概述"),
        results_raw=_require_text(body, "results_raw", "成果与数据"),
        issues_raw=body.get("issues_raw", "")[:2000],
        lessons_raw=body.get("lessons_raw", "")[:2000],
    )
    _save_briefing(db, user, data)
    _audit(db, user, "briefing.project_closure", f"briefing:{data['briefing_id']}", project=project[:64])
    return data


@router.post("/briefings/push")
def api_push_jdy(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """人工确认后推送简道云。

    body 两种用法：
    - {"briefing_id": N, "include_tasks": true} 推送已落库文稿（汇总 + 可选任务表逐条）
    - {"payload": {...} 或 "payloads": [...], "kind": "task|knowledge"} 直接推送自定义内容
    推送回执（entry_id / 模式）回写 briefings 表（附件5 §8.5 经理可查推送量）。
    """
    kind = body.get("kind", "task")
    row = None
    payloads: list = []
    if body.get("briefing_id"):
        row = db.get(Briefing, int(body["briefing_id"]))
        if not row or (row.user_id != user.id and user.role != "admin"):
            raise HTTPException(404, "文稿不存在")
        payloads = ([row.jdy_payload] if (row.jdy_payload and body.get("include_payload", True)) else []) + (
            list(row.jdy_tasks or []) if body.get("include_tasks", True) else []
        )
        kind = "task"
    else:
        raw = body.get("payloads") or ([body["payload"]] if body.get("payload") else [])
        payloads = [p for p in raw if isinstance(p, dict) and p]
    if not payloads:
        raise HTTPException(422, "缺少可推送的内容（payload / briefing_id）")
    if len(payloads) > 30:
        raise HTTPException(422, "单次最多推送 30 条")
    result = push_to_jdy(payloads if len(payloads) > 1 else payloads[0], kind=kind)
    if row is not None and result.get("ok"):
        row.pushed = True
        row.push_mode = result.get("mode", "")
        row.jdy_entry_ids = result.get("entry_ids") or []
        row.pushed_at = datetime.utcnow()
        db.commit()
    _audit(db, user, "briefing.push_jdy", f"briefing:{row.id}" if row else "briefing",
           kind=kind, count=result.get("count", 1), ok=bool(result.get("ok")),
           mode=result.get("mode", ""))
    return result


@router.get("/briefings/history", response_model=list[BriefingOut])
def briefing_history(kind: str = "", limit: int = 50,
                     db: Session = Depends(get_db), user: User = Depends(current_user)):
    """我的自动化文稿历史（生成与推送状态）。"""
    stmt = select(Briefing).where(Briefing.user_id == user.id)
    if kind:
        stmt = stmt.where(Briefing.kind == kind)
    return db.execute(stmt.order_by(Briefing.created_at.desc())
                      .limit(min(limit, 200))).scalars().all()


@router.get("/briefings/stats")
def briefing_stats(department: str = "",
                   db: Session = Depends(get_db),
                   user: User = Depends(require_perm("briefing.stats.dept"))):
    """附件5 §8.5：部门经理看本部门早宣/晚总推送量与今日未推送名单。

    权限隔离：manager 强制锁定本部门（department 参数被忽略）；admin 可看全部或按部门过滤。
    """
    from datetime import date as _date
    dept_filter = department.strip()
    if user.role != "admin":
        dept_filter = user.department or ""
    today = _date.today().isoformat()
    q = select(Briefing.department, Briefing.kind, Briefing.pushed, func.count())
    if user.role != "admin" or dept_filter:
        q = q.where(Briefing.department == dept_filter)
    rows = db.execute(q.group_by(Briefing.department, Briefing.kind, Briefing.pushed)).all()
    by_dept: dict = {}
    for dept, k, pushed, n in rows:
        d = by_dept.setdefault(dept or "(未填)", {})
        d[f"{k}.{'pushed' if pushed else 'generated'}"] = n
    # 今日已推送早宣的用户（同样按部门过滤）
    tq = select(Briefing.user_id, Briefing.kind).where(
        Briefing.created_at >= today, Briefing.pushed == True)  # noqa: E712
    if user.role != "admin" or dept_filter:
        tq = tq.join(User, Briefing.user_id == User.id).where(User.department == dept_filter)
    pushed_today: dict = {}
    for uid, k in db.execute(tq).all():
        pushed_today.setdefault(uid, []).append(k)
    return {"by_department": by_dept, "today": today, "department": dept_filter,
            "pushed_today_users": pushed_today}


# ---------- 用户管理（RBAC · 仅 admin；角色分配不再依赖环境变量白名单） ----------
@router.get("/admin/users", response_model=list[UserAdminOut])
def admin_list_users(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return db.execute(select(User).order_by(User.id)).scalars().all()


@router.patch("/admin/users/{user_id}", response_model=UserAdminOut)
def admin_patch_user(user_id: int, body: UserPatchIn,
                     db: Session = Depends(get_db), user: User = Depends(require_admin)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    # 防误锁：不能改自己的角色 / 停用自己
    if target.id == user.id:
        if body.role is not None and body.role != target.role:
            raise HTTPException(422, "不能修改自己的角色，请由其他管理员操作")
        if body.status is not None and body.status != "active":
            raise HTTPException(422, "不能停用自己的账号")
    # 末位 admin 保护：降级/停用 admin 前，必须还有另一名可用 admin
    demote = (body.role is not None and body.role != "admin") or (
        body.status is not None and body.status != "active")
    if (target.role or "") == "admin" and demote:
        others = db.execute(
            select(func.count()).select_from(User).where(
                User.role == "admin", User.status == "active", User.id != target.id)
        ).scalar() or 0
        if others == 0:
            raise HTTPException(422, "系统至少保留一名可用管理员")
    changed: dict = {}
    if body.role is not None and body.role != (target.role or ""):
        changed["role"] = f"{target.role}->{body.role}"
        target.role = body.role
    if body.status is not None and body.status != (target.status or "active"):
        changed["status"] = f"{target.status or 'active'}->{body.status}"
        target.status = body.status
    if body.department is not None and body.department.strip() and body.department.strip() != target.department:
        changed["department"] = f"{target.department}->{body.department.strip()}"
        target.department = body.department.strip()
    if body.position is not None and body.position.strip() and body.position.strip() != target.position:
        changed["position"] = f"{target.position}->{body.position.strip()}"
        target.position = body.position.strip()
    if changed:
        db.commit()
        db.refresh(target)
        _audit(db, user, "admin.user.patch", f"user:{target.id}", **changed)
    return target


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
    result = generate_with_review(db, user, sc, body.variables or {}, model=body.model,
                                  extra_instructions=body.extra_instructions or "")
    _audit(db, user, "mature.generate", f"rule:{code}",
           session_id=result.get("session_id"), model=body.model or sc.default_model)
    return result


@router.post("/mature-rules/review/{session_id}")
def mature_review(session_id: int, body: ReviewIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        result = apply_review(db, user, session_id, ReviewDecision(action=body.action, note=body.note), final_text=body.final_text)
    except ReviewForbidden as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))
    _audit(db, user, "mature.review", f"session:{session_id}", review_action=body.action)
    return result

# ---------- 任务管理智能体 P0：今日工作安排 ----------
@router.post("/tasks/capture")
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
            is_meeting=bool(it.get("is_meeting")),
            is_other_request=bool(it.get("is_other_request")),
            is_today_fixed=bool(it.get("is_today_fixed")),
            jdy_data_id=str(it.get("jdy_data_id") or "")[:64],
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
    _audit(db, user, "task.ingest", "task", created=created, skipped_dup=skipped)
    return {"created": created, "skipped_dup": skipped}


@router.get("/tasks/today")
def tasks_today(
    leader_mode: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """首页「今日工作安排」：三分类 + 排序 + 时间轴。

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
        "is_meeting": bool(getattr(r, "is_meeting", False)),
        "is_other_request": bool(getattr(r, "is_other_request", False)),
        "is_today_fixed": bool(getattr(r, "is_today_fixed", False)),
        "ai_priority_score": r.ai_priority_score,
        "description": r.description or "",
        "ai_source_type": r.ai_source_type,
        "source": r.source,
        "project_name": r.project_name,
        "jdy_data_id": getattr(r, "jdy_data_id", "") or "",
        "manual_order": (r.ai_schedule_block or {}).get("manual_order")
        if isinstance(r.ai_schedule_block, dict) else None,
    } for r in rows]
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
    if body.get("due_time"):
        row.due_time = str(body["due_time"])[:32]
        sb = dict(row.ai_schedule_block or {})
        sb["planned_for"] = str(body["due_time"])[:10]
        row.ai_schedule_block = sb
    db.commit()
    _audit(db, user, "task.feedback", f"task:{task_id}",
           **{k: v for k, v in body.items() if isinstance(v, (str, int, float, bool))})
    return {"ok": True}


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

    # 手册 1.6 方向：简道云来源任务的状态回写（失败不阻塞本地，留痕即可）
    jdy_wb = None
    if getattr(row, "jdy_data_id", ""):
        res = jdy.update_form(
            jdy.entry_id_task, row.jdy_data_id,
            {JDY_FIELD_MAP.get("status", "任务状态"): status},
        )
        jdy_wb = {"ok": res.ok, "mode": res.mode, "message": res.message}
        _audit(db, user, "task.jdy_writeback", f"task:{task_id}",
               data_id=row.jdy_data_id, status=status, ok=res.ok, mode=res.mode)
    return {"ok": True, "status": status, "jdy_writeback": jdy_wb}


@router.post("/tasks/reorder")
def tasks_reorder(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """时间轴拖拽排序：按提交顺序写入 manual_order（存 ai_schedule_block）。"""
    ids = body.get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(422, "缺少 ids")
    rows = db.execute(
        select(TaskItem).where(TaskItem.user_id == user.id, TaskItem.id.in_(ids[:200]))
    ).scalars().all()
    by_id = {r.id: r for r in rows}
    updated = 0
    skipped_b0 = 0
    for i, tid in enumerate(ids[:200]):
        row = by_id.get(int(tid) if str(tid).isdigit() else -1)
        if not row:
            continue
        # B0 固定事项不可打乱（附件3 §5.2）：固定时间/会议/今日固定 不参与手动排序
        if row.ai_fixed_start or row.is_meeting or row.is_today_fixed:
            skipped_b0 += 1
            continue
        sb = dict(row.ai_schedule_block or {})
        sb["manual_order"] = (i + 1) * 10
        row.ai_schedule_block = sb
        updated += 1
    db.commit()
    _audit(db, user, "task.reorder", "task", count=updated, skipped_b0=skipped_b0)
    return {"ok": True, "updated": updated, "skipped_b0": skipped_b0}


@router.post("/tasks/sync-jdy")
def tasks_sync_jdy(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """从简道云「任务管理」拉取任务镜像入池（手册：任务池为简道云镜像）。

    - 按 JDY_FIELD_MAP 映射字段；jdy_data_id / 任务编号 / 标题三级去重
    - owner 含当前用户姓名的行才归入本人（成员字段为结构化 id 时放行由人工确认）
    - body: {mine_only: true(默认), limit: 100}
    """
    if jdy.mock:
        _audit(db, user, "task.sync_jdy", "task", mode="mock")
        return {"mode": "mock", "synced": 0, "skipped": 0,
                "hint": "JDY 为 MOCK 模式：配置 JDY_APP_ID/JDY_API_KEY 后可真实拉取"}
    mine_only = bool(body.get("mine_only", True))
    rows = jdy.query_form(jdy.entry_id_task, limit=min(int(body.get("limit") or 100), 100))
    synced = 0
    skipped = 0
    for raw in rows:
        t = jdy_row_to_task(raw)
        if not t["title"]:
            skipped += 1
            continue
        if mine_only and t["owner"] and user.name not in t["owner"]:
            skipped += 1
            continue
        key = t["external_task_no"] or t["jdy_data_id"] or t["title"][:64]
        exists = db.execute(
            select(TaskItem).where(
                TaskItem.user_id == user.id,
                (TaskItem.jdy_data_id == t["jdy_data_id"]) if t["jdy_data_id"]
                else (TaskItem.ai_dedup_key == key),
            )
        ).scalar_one_or_none()
        if exists:
            # 状态/截止时间跟随简道云更新（单向镜像）
            exists.status = t["status"] or exists.status
            exists.due_time = t["due_time"] or exists.due_time
            skipped += 1
            continue
        row = TaskItem(
            user_id=user.id,
            title=t["title"],
            description=t["description"],
            project_name=t["project_name"],
            status=t["status"] or "待办",
            start_time=t["start_time"],
            due_time=t["due_time"],
            estimated_hours=t["estimated_hours"],
            priority=t["priority"],
            external_task_no=t["external_task_no"],
            jdy_data_id=t["jdy_data_id"],
            source="jdy",
            ai_source_type="new_input",
            ai_dedup_key=key[:64],
        )
        row.ai_priority_score = score_task({
            "due_time": row.due_time, "ai_importance": 3, "ai_urgency": 3,
            "ai_impact_scope": "个人", "estimated_hours": row.estimated_hours,
            "ai_complexity": 3,
        })
        db.add(row)
        synced += 1
    db.commit()
    _audit(db, user, "task.sync_jdy", "task", synced=synced, skipped=skipped, total=len(rows))
    return {"mode": "live", "synced": synced, "skipped": skipped, "total": len(rows)}
