# -*- coding: utf-8 -*-
"""添加任务项目（资料文件夹 → Mimo项目 → 工作流）API。"""
from pathlib import Path

ROOT = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")

# --- schemas ---
p = ROOT / "app" / "schemas.py"
t = p.read_text(encoding="utf-8")
if "TaskProjectIn" not in t:
    t += '''

class TaskProjectIn(BaseModel):
    name: str
    folder_path: str = ""
    folder_name: str = ""
    materials: list = Field(default_factory=list)
    department: str = ""
    position: str = ""
    scenario_id: Optional[int] = None


class TaskProjectUpdate(BaseModel):
    mimo_project: Optional[str] = None
    materials: Optional[list] = None
    scenario_id: Optional[int] = None
    workflow_stage: Optional[str] = None
    status: Optional[str] = None
    progress_note: Optional[str] = None
    output: Optional[dict] = None


class TaskProjectOut(BaseModel):
    id: int
    code: str
    name: str
    department: str
    position: str
    folder_path: str
    folder_name: str
    materials: list
    mimo_project: str
    mimo_ready: int
    scenario_id: Optional[int]
    workflow_stage: str
    status: str
    progress: list
    outputs: list
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
'''
    p.write_text(t, encoding="utf-8")
    print("schemas ok")

# --- api ---
p = ROOT / "app" / "routers" / "api.py"
t = p.read_text(encoding="utf-8")
if "/task-projects" not in t:
    t = t.replace(
        "from ..database import ExportCheck, Scenario",
        "from ..database import ExportCheck, Scenario, TaskProject",
    )
    old_imp = """from ..schemas import (
    AssetCreate, AssetOut, DevLoginIn, ExportCheckIn, ExportCheckOut, FinalizeIn,
    GenerateIn, LoginOut, RatingIn, ScenarioDetailOut, ScenarioOut, SessionCreate,
    SessionOut, UserOut,
)"""
    new_imp = """from ..schemas import (
    AssetCreate, AssetOut, DevLoginIn, ExportCheckIn, ExportCheckOut, FinalizeIn,
    GenerateIn, LoginOut, RatingIn, ScenarioDetailOut, ScenarioOut, SessionCreate,
    SessionOut, TaskProjectIn, TaskProjectOut, TaskProjectUpdate, UserOut,
)"""
    if old_imp in t:
        t = t.replace(old_imp, new_imp)
    else:
        print("WARN schemas import not matched")
    t = t.rstrip() + '''

# ---------- 任务项目（资料文件夹 → Mimo项目 → 工作流） ----------
@router.post("/task-projects", response_model=TaskProjectOut)
def create_task_project(body: TaskProjectIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from datetime import datetime as _dt
    import uuid as _uuid
    code = "TP" + _dt.utcnow().strftime("%Y%m%d") + _uuid.uuid4().hex[:4].upper()
    folder_name = body.folder_name
    if not folder_name and body.folder_path:
        folder_name = body.folder_path.replace("\\\\", "/").rstrip("/").split("/")[-1]
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
'''
    p.write_text(t, encoding="utf-8")
    print("api ok")

# --- seed usage_steps 前缀统一为开工三步 ---
seed = ROOT / "app" / "seed" / "scenarios.py"
s = seed.read_text(encoding="utf-8")
if "资料文件夹" not in s:
    # 在 WORKFLOW_MAP 注释后补充全局说明
    s = s.replace(
        "# code -> (workflow_stage, usage_steps)",
        "# 标准开工：①建任务资料文件夹 ②Mimo V2.6 新建项目并绑定 ③按 usage_steps 推进工作流\n"
        "# code -> (workflow_stage, usage_steps)",
    )
    # usage_steps 自动加前缀（在 seed_scenarios 赋值处）
    s = s.replace(
        'workflow_stage=WORKFLOW_MAP.get(item["code"], ("", ""))[0],\n            usage_steps=WORKFLOW_MAP.get(item["code"], ("", ""))[1],',
        'workflow_stage=WORKFLOW_MAP.get(item["code"], ("", ""))[0],\n'
        '            usage_steps="①资料文件夹 ②Mimo新建项目 ③" + (WORKFLOW_MAP.get(item["code"], ("", ""))[1] or "按场景卡推进"),',
    )
    seed.write_text(s, encoding="utf-8")
    print("seed ok")
else:
    print("seed already ok")

print("all done")
