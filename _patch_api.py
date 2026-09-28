# -*- coding: utf-8 -*-
from pathlib import Path

root = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")
p = root / "app" / "routers" / "api.py"
text = p.read_text(encoding="utf-8")

text = text.replace(
    "from ..services.model_gateway import gateway",
    "from ..services.export_control import compliance_prompt_snippet, screen\nfrom ..services.model_gateway import gateway",
)
text = text.replace(
    "from ..database import Scenario",
    "from ..database import ExportCheck, Scenario",
)
old_imp = """from ..schemas import (
    AssetCreate, AssetOut, DevLoginIn, FinalizeIn, GenerateIn, LoginOut,
    RatingIn, ScenarioDetailOut, ScenarioOut, SessionCreate, SessionOut, UserOut,
)"""
new_imp = """from ..schemas import (
    AssetCreate, AssetOut, DevLoginIn, ExportCheckIn, ExportCheckOut, FinalizeIn,
    GenerateIn, LoginOut, RatingIn, ScenarioDetailOut, ScenarioOut, SessionCreate,
    SessionOut, UserOut,
)"""
if old_imp in text:
    text = text.replace(old_imp, new_imp)
else:
    print("WARN: schemas import block not matched")

extra = '''

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
    case_no = "EXP" + _dt.utcnow().strftime("%Y%m%d%H%M%S")
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
'''

if "/export-checks" not in text:
    text = text.rstrip() + "\n" + extra
p.write_text(text, encoding="utf-8")
print("api.py patched, len", len(text))
