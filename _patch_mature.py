# -*- coding: utf-8 -*-
"""接入成熟规则：maturity 字段 + 自动成稿/审核放行 API + 种子。"""
from pathlib import Path

ROOT = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")

# 1) database: maturity column
p = ROOT / "app" / "database.py"
t = p.read_text(encoding="utf-8")
if "maturity" not in t:
    t = t.replace(
        '    # 工作流节点与使用步骤（T13 岗位工作流矩阵）\n'
        '    workflow_stage = Column(String(64), default="")\n'
        '    usage_steps = Column(String(256), default="")',
        '    # 工作流节点与使用步骤（T13 岗位工作流矩阵）\n'
        '    workflow_stage = Column(String(64), default="")\n'
        '    usage_steps = Column(String(256), default="")\n'
        '    # 成熟规则分级：draft / validated / production\n'
        '    maturity = Column(String(16), default="draft")',
    )
    p.write_text(t, encoding="utf-8")
    print("database ok")
else:
    print("database has maturity")

# 2) schemas
p = ROOT / "app" / "schemas.py"
t = p.read_text(encoding="utf-8")
if "maturity" not in t:
    t = t.replace(
        '    workflow_stage: str = ""\n    usage_steps: str = ""',
        '    workflow_stage: str = ""\n    usage_steps: str = ""\n    maturity: str = "draft"',
    )
    t += '''

class MatureGenerateIn(BaseModel):
    variables: dict = Field(default_factory=dict)
    model: Optional[str] = None


class ReviewIn(BaseModel):
    action: str = Field(description="approve / revise / reject")
    note: str = ""
    final_text: str = ""
'''
    p.write_text(t, encoding="utf-8")
    print("schemas ok")
else:
    print("schemas has maturity")

# 3) api
p = ROOT / "app" / "routers" / "api.py"
t = p.read_text(encoding="utf-8")
if "/mature-rules" not in t:
    t = t.replace(
        "from ..services.export_control import compliance_prompt_snippet, screen",
        "from ..services.export_control import compliance_prompt_snippet, screen\n"
        "from ..services.mature_rules import ReviewDecision, apply_review, generate_with_review, seed_mature_rules",
    )
    if "MatureGenerateIn" not in t:
        t = t.replace(
            "    SessionOut, TaskProjectIn, TaskProjectOut, TaskProjectUpdate, UserOut,\n)",
            "    SessionOut, TaskProjectIn, TaskProjectOut, TaskProjectUpdate, UserOut,\n    MatureGenerateIn, ReviewIn,\n)",
        )
    t = t.rstrip() + '''

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
'''
    p.write_text(t, encoding="utf-8")
    print("api ok")
else:
    print("api has mature")

# 4) main startup seed mature rules
p = ROOT / "app" / "main.py"
t = p.read_text(encoding="utf-8")
if "seed_mature_rules" not in t:
    t = t.replace(
        "from .seed.scenarios import seed_scenarios",
        "from .seed.scenarios import seed_scenarios\nfrom .services.mature_rules import seed_mature_rules",
    )
    t = t.replace(
        "        created = seed_scenarios(db)\n        if created:\n            print(f\"[seed] 已初始化场景卡 {created} 张\")",
        "        created = seed_scenarios(db)\n"
        "        if created:\n            print(f\"[seed] 已初始化场景卡 {created} 张\")\n"
        "        n_rules = seed_mature_rules(db)\n"
        "        if n_rules:\n            print(f\"[seed] 成熟规则 +{n_rules}\")",
    )
    p.write_text(t, encoding="utf-8")
    print("main ok")

print("mature rules wired")
