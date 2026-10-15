# -*- coding: utf-8 -*-
"""合规审查 API：审查前移（项目初步分析阶段完成审查）+ 规则/资料资产配置。

分工口径（门禁：审查前移）：
- 审查只在「项目初步分析阶段」执行一次：POST /task-projects/{code}/screening
  （或既有 /export-checks 带 task_project_code 绑定）；
- 工作台/场景生成只读取审查结果：GET /task-projects/{code}/compliance
  与 generate 中的合规闸口，均不重复调用 screen()；
- 规则与资料（选型软件等）为可调用资产：GET /compliance/rules | /compliance/resources；
  维护（新增/修改/启停）限 compliance/admin（权限点 compliance.rules）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_perm
from ..database import (
    AuditLog, ComplianceRule, ExportCheck, TaskProject, User, get_db,
)
from ..services import compliance_rules as cr
from ..services.export_control import screen

router = APIRouter()


def _audit(db: Session, user: User, action: str, resource: str = "", **detail):
    db.add(AuditLog(user_id=user.id, action=action, resource=resource, detail=detail))
    db.commit()


def _rule_out(r: ComplianceRule) -> dict:
    return {
        "id": r.id, "category": r.category, "code": r.code, "name": r.name,
        "value": r.value or {}, "description": r.description or "",
        "enabled": bool(r.enabled), "sort": r.sort or 0,
        "updated_by": r.updated_by or "",
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ---------------------------------------------------------------------------
# 规则与资料资产（可调用）
# ---------------------------------------------------------------------------
@router.get("/compliance/rules")
def list_rules(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """全部规则与资料（登录可读，按 category 分组）。"""
    rows = db.execute(
        select(ComplianceRule).order_by(ComplianceRule.category, ComplianceRule.sort)
    ).scalars().all()
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r.category, []).append(_rule_out(r))
    return {
        "categories": [
            {"category": c, "label": cr.CATEGORY_LABELS.get(c, c), "items": items}
            for c, items in groups.items()
        ],
        "total": len(rows),
        "can_edit": user.role in ("compliance", "admin"),
    }


@router.get("/compliance/resources")
def list_resources(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """资料资产（选型软件/法规文档/模板等）——审查与工作台可调用的资产清单。"""
    rows = db.execute(
        select(ComplianceRule)
        .where(ComplianceRule.category == "resource", ComplianceRule.enabled == True)  # noqa: E712
        .order_by(ComplianceRule.sort)
    ).scalars().all()
    return [_rule_out(r) for r in rows]


class RuleUpsertIn(BaseModel):
    category: str = Field(pattern="^(country_list|item_hints|end_use_redline|red_flag|checklist|decision_note|resource)$")
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=256)
    value: dict = Field(default_factory=dict)
    description: str = Field(default="", max_length=512)
    enabled: bool = True
    sort: int = 0


@router.post("/compliance/rules")
def upsert_rule(body: RuleUpsertIn, db: Session = Depends(get_db),
                user: User = Depends(require_perm("compliance.rules"))):
    """新增/更新规则（按 category+code upsert）。合规官/管理员专属。"""
    row = db.execute(
        select(ComplianceRule).where(ComplianceRule.category == body.category,
                                     ComplianceRule.code == body.code)
    ).scalar_one_or_none()
    created = row is None
    if row is None:
        row = ComplianceRule(category=body.category, code=body.code)
        db.add(row)
    row.name = body.name or row.name or body.code
    row.value = body.value
    row.description = body.description
    row.enabled = body.enabled
    row.sort = body.sort
    row.updated_by = user.name
    db.commit()
    db.refresh(row)
    cr.invalidate_cache()
    _audit(db, user, "compliance.rule.upsert", f"rule:{body.category}:{body.code}",
           created=created, enabled=body.enabled)
    return _rule_out(row)


class RulePatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=256)
    value: dict | None = None
    description: str | None = Field(default=None, max_length=512)
    enabled: bool | None = None
    sort: int | None = None


@router.patch("/compliance/rules/{rule_id}")
def patch_rule(rule_id: int, body: RulePatchIn, db: Session = Depends(get_db),
               user: User = Depends(require_perm("compliance.rules"))):
    row = db.get(ComplianceRule, rule_id)
    if not row:
        raise HTTPException(404, "规则不存在")
    changed = {}
    if body.name is not None and body.name.strip():
        row.name = body.name.strip(); changed["name"] = row.name
    if body.value is not None:
        row.value = body.value; changed["value"] = "已更新"
    if body.description is not None:
        row.description = body.description.strip(); changed["description"] = "已更新"
    if body.enabled is not None:
        row.enabled = body.enabled; changed["enabled"] = body.enabled
    if body.sort is not None:
        row.sort = body.sort; changed["sort"] = body.sort
    if changed:
        row.updated_by = user.name
        db.commit()
        db.refresh(row)
        cr.invalidate_cache()
        _audit(db, user, "compliance.rule.patch", f"rule:{row.category}:{row.code}", **changed)
    return _rule_out(row)


@router.post("/compliance/rules/seed")
def reseed_rules(db: Session = Depends(get_db),
                 user: User = Depends(require_perm("compliance.rules"))):
    """补种缺失的默认规则（幂等；不覆盖人工修改过的同名规则）。"""
    n = cr.seed_compliance_rules(db)
    _audit(db, user, "compliance.rule.seed", "rule", created=n)
    return {"created": n}


# ---------------------------------------------------------------------------
# 审查前移：项目初步分析阶段完成合规审查
# ---------------------------------------------------------------------------
class ProjectScreeningIn(BaseModel):
    """项目初步分析合规初筛入参（缺省取项目登记的客户/国别）。"""
    customer_name: str = Field(default="", max_length=128)
    middleman: str = Field(default="", max_length=128)
    country: str = Field(default="", max_length=64)
    arrival_country: str = Field(default="", max_length=64)
    end_user_country: str = Field(default="", max_length=64)
    end_user: str = Field(default="", max_length=128)
    end_use: str = Field(default="", max_length=256)
    product_desc: str = Field(default="", max_length=256)
    hs_code: str = Field(default="", max_length=32)
    extra_red_flags: list[str] = Field(default_factory=list, max_length=20)
    force: bool = False  # 已有放行结论时，情况变化需重新审查才置 true


def _get_project(db: Session, code: str, user: User) -> TaskProject:
    row = db.execute(select(TaskProject).where(TaskProject.code == code)).scalar_one_or_none()
    if not row or (row.user_id != user.id and user.role not in ("admin", "compliance")):
        raise HTTPException(404, "任务项目不存在")
    return row


def _bound_check(db: Session, project: TaskProject):
    """项目当前绑定的审查单（唯一事实源）。"""
    if not project.export_check_case_no:
        return None
    return db.execute(
        select(ExportCheck).where(ExportCheck.case_no == project.export_check_case_no)
    ).scalar_one_or_none()


@router.post("/task-projects/{code}/screening")
def project_screening(code: str, body: ProjectScreeningIn,
                      db: Session = Depends(get_db), user: User = Depends(current_user)):
    """项目初步分析阶段发起合规初筛：生成本项目的审查单并绑定。

    - 审查在此阶段完成一次；已有「已放行」结论时默认拒绝重复审查
      （情况确已变化时 force=true 重新审查并换绑新单）；
    - 审查规则取自合规规则资产库（load_rules），合规官可在线维护；
    - 项目登记的客户/国别自动回填为本审查要素（body 可覆盖）。
    """
    project = _get_project(db, code, user)
    existing = _bound_check(db, project)
    if existing is not None and not body.force:
        state = cr.project_compliance_state(existing)
        if state["state"] == "approved":
            raise HTTPException(
                409, f"项目已完成合规审查并放行（{existing.case_no}），无需重复审查。"
                     "情况发生变化时以 force=true 重新审查。")
        if state["state"] in ("reviewing", "escalated"):
            raise HTTPException(
                409, f"项目已有审查单在途（{existing.case_no}，{state['message']}），"
                     "请等待合规官终审，不重复发起。")

    customer = (body.customer_name or project.customer_name or "").strip()
    country = (body.country or project.country or "").strip()
    if not customer or not country:
        raise HTTPException(422, "客户名称与目的地/签约国为必填（可在任务项目中登记或本表单填写）")

    # 审查引擎读取规则资产库（配置化）；本阶段是 screen() 的唯一调用点
    rules = cr.load_rules(db)
    result = screen(
        customer_name=customer,
        country=country,
        end_user=body.end_user,
        end_use=body.end_use,
        product_desc=body.product_desc,
        hs_code=body.hs_code,
        extra_red_flags=body.extra_red_flags,
        middleman=body.middleman,
        arrival_country=body.arrival_country,
        end_user_country=body.end_user_country,
        rules=rules,
    )
    import uuid as _uuid
    case_no = "EXP" + datetime.utcnow().strftime("%Y%m%d%H%M%S") + _uuid.uuid4().hex[:4].upper()
    row = ExportCheck(
        case_no=case_no,
        user_id=user.id,
        task_project_code=project.code,
        customer_name=customer,
        middleman=body.middleman,
        arrival_country=body.arrival_country,
        end_user_country=body.end_user_country,
        country=country,
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
    # 回填项目：初步分析要素 + 绑定审查单（工作台凭 export_check_case_no 调结果）
    project.customer_name = project.customer_name or customer
    project.country = project.country or country
    project.export_check_case_no = case_no
    project.progress = list(project.progress or []) + [{
        "step": "合规初筛（初步分析阶段）", "status": "done",
        "note": f"审查单 {case_no}：{result.decision}",
    }]
    db.commit()
    db.refresh(row)
    _audit(db, user, "compliance.project_screening", f"export:{case_no}",
           project=code, decision=result.decision, rules_source=rules.get("source", ""))
    from ..schemas import ExportCheckOut  # 延迟导入避免循环
    out = ExportCheckOut.model_validate(row).model_dump()
    out["compliance"] = cr.project_compliance_state(row)
    out["rules_source"] = rules.get("source", "default")
    return out


@router.get("/task-projects/{code}/compliance")
def project_compliance(code: str, db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    """项目合规状态查询 —— 工作台/场景生成只调用本结果，不重复审查。"""
    project = _get_project(db, code, user)
    check = _bound_check(db, project)
    state = cr.project_compliance_state(check)
    state["project_code"] = project.code
    state["customer_name"] = project.customer_name or ""
    state["country"] = project.country or ""
    return state
