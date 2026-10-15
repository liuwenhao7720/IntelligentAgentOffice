# -*- coding: utf-8 -*-
"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _none_to_list(v):
    """防御：历史脏数据 JSON 列为 NULL 时按空列表输出，避免响应校验 500。"""
    return [] if v is None else v


def _none_to_dict(v):
    return {} if v is None else v


class DevLoginIn(BaseModel):
    # 输入验证：长度上限防注入/脏数据；role 仅允许白名单取值（服务端仍会再钳制）
    name: str = Field(default="演示员工", min_length=1, max_length=64)
    department: str = Field(default="项目事业部", max_length=64)
    position: str = Field(default="项目经理", max_length=64)
    role: str = Field(default="staff", pattern="^(staff|admin)$")


class UserOut(BaseModel):
    id: int
    name: str
    department: str
    position: str
    role: str
    model_config = {"from_attributes": True}


class LoginOut(BaseModel):
    token: str
    user: UserOut


class UserAdminOut(BaseModel):
    """管理员用户管理视图（含状态与企微绑定情况，不含敏感字段）。"""
    id: int
    name: str
    department: str
    position: str
    role: str
    status: str = "active"
    wecom_userid: str = ""
    created_at: datetime
    model_config = {"from_attributes": True}


class UserPatchIn(BaseModel):
    """管理员维护用户：角色/状态/组织信息。所有字段可选，传谁改谁。"""
    role: Optional[str] = Field(default=None, pattern="^(staff|manager|compliance|admin)$")
    status: Optional[str] = Field(default=None, pattern="^(active|disabled)$")
    department: Optional[str] = Field(default=None, max_length=64)
    position: Optional[str] = Field(default=None, max_length=64)


class ScenarioOut(BaseModel):
    id: int
    code: str
    title: str
    department: str
    roles: str
    timing: str
    goal: str
    category: str
    variables: list
    default_model: str
    fallback_model: str
    output_format: str
    quality_notes: str
    example_input: str
    example_output: str
    version: str
    status: str
    author: str = "system"
    use_count: int
    kpi_links: list = []
    security_level: str = "normal"
    workflow_stage: str = ""
    usage_steps: str = ""
    maturity: str = "draft"
    model_config = {"from_attributes": True}

    _v_lists = field_validator("variables", "kpi_links", mode="before")(_none_to_list)


class ScenarioDetailOut(ScenarioOut):
    prompt_template: str


class SessionCreate(BaseModel):
    scenario_id: Optional[int] = None
    title: str = Field(default="", max_length=128)
    model: str = Field(default="mimo", max_length=32)
    variables: dict = Field(default_factory=dict)
    # 附件3 §3.4：个人隐私场景可申请「仅元数据留痕」（审计轨迹仍保留，内容不落库）
    privacy: str = Field(default="standard", pattern="^(standard|metadata_only)$")
    # 所属任务项目（工作台合规闸口凭它读取项目审查结果）
    task_project_code: str = Field(default="", max_length=32)


class GenerateIn(BaseModel):
    model: Optional[str] = Field(default=None, max_length=32)
    extra_instructions: str = Field(default="", max_length=4000)
    variables: Optional[dict] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    model: str
    is_final: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: int
    title: str
    model: str
    status: str
    scenario_id: Optional[int]
    variables: dict
    rating: Optional[int]
    privacy: str = "standard"
    review_status: str = ""
    reviewed_by: str = ""
    tokens_in: int
    tokens_out: int
    channel: str = "workbench"
    task_project_code: str = ""
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)
    model_config = {"from_attributes": True}

    _v_vars = field_validator("variables", mode="before")(_none_to_dict)


class FinalizeIn(BaseModel):
    content: str = Field(description="人工定稿内容", min_length=1, max_length=100000)


class RatingIn(BaseModel):
    rating: int = Field(ge=1, le=5)


class AssetCreate(BaseModel):
    session_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=100000)
    visibility: str = Field(default="dept", pattern="^(private|dept|company)$")
    tags: list[str] = Field(default_factory=list, max_length=20)
    distributed_to: list[str] = Field(default_factory=list, max_length=10)


class AssetOut(BaseModel):
    id: int
    title: str
    content: str
    session_id: Optional[int] = None
    department: str
    visibility: str
    tags: list
    distributed_to: list = []
    featured: bool
    created_at: datetime
    model_config = {"from_attributes": True}

    _v_lists = field_validator("tags", "distributed_to", mode="before")(_none_to_list)


class ExportCheckIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=128)
    middleman: str = Field(default="", max_length=128)          # 中间商（EXP-01）
    country: str = Field(min_length=1, max_length=64)           # 目的地/签约国
    arrival_country: str = Field(default="", max_length=64)     # 运抵国（EXP-03）
    end_user_country: str = Field(default="", max_length=64)    # 最终用户所在国（EXP-03）
    end_user: str = Field(default="", max_length=128)
    end_use: str = Field(default="", max_length=256)
    product_desc: str = Field(default="", max_length=256)
    hs_code: str = Field(default="", max_length=32)
    extra_red_flags: list[str] = Field(default_factory=list, max_length=20)
    # 审查前移：关联任务项目（项目初步分析阶段审查的凭据；绑定后工作台只读结果）
    task_project_code: str = Field(default="", max_length=32)


class ExportCheckOut(BaseModel):
    id: int
    case_no: str
    customer_name: str
    middleman: str = ""
    country: str
    arrival_country: str = ""
    end_user_country: str = ""
    end_user: str
    end_use: str
    product_desc: str
    country_risk: str
    sanctions_hit: str
    item_control: str
    license_needed: str
    red_flags: list
    decision: str
    decision_note: str
    checklist: list
    status: str
    reviewed_by: str = ""
    review_note: str = ""
    reviewed_at: Optional[datetime] = None
    task_project_code: str = ""
    created_at: datetime
    model_config = {"from_attributes": True}

    _v_lists = field_validator("red_flags", "checklist", mode="before")(_none_to_list)


class ExportReviewIn(BaseModel):
    """合规官终审（附件1 §2.4/G5、T20）：放行/否决/附加条件。"""
    action: str = Field(pattern="^(approve|reject|conditions)$")
    note: str = Field(default="", max_length=2000)
    decision_override: str = Field(default="", pattern="^(|pass|manual_review|escalate|reject)$")


class TaskProjectIn(BaseModel):
    name: str
    folder_path: str = ""
    folder_name: str = ""
    materials: list = Field(default_factory=list)
    department: str = ""
    position: str = ""
    scenario_id: Optional[int] = None
    # 项目初步分析要素（涉外项目建议填写，供合规审查前移调用）
    customer_name: str = Field(default="", max_length=128)
    country: str = Field(default="", max_length=64)


class TaskProjectUpdate(BaseModel):
    mimo_project: Optional[str] = None
    materials: Optional[list] = None
    scenario_id: Optional[int] = None
    workflow_stage: Optional[str] = None
    status: Optional[str] = None
    progress_note: Optional[str] = None
    output: Optional[dict] = None
    customer_name: Optional[str] = Field(default=None, max_length=128)
    country: Optional[str] = Field(default=None, max_length=64)


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
    customer_name: str = ""
    country: str = ""
    export_check_case_no: str = ""
    # 合规审查结果摘要（列表接口批量装配；工作台只读取该结果，不重复审查）
    compliance: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

    _v_lists = field_validator("materials", "progress", "outputs", mode="before")(_none_to_list)


class MatureGenerateIn(BaseModel):
    variables: dict = Field(default_factory=dict)
    model: Optional[str] = None
    extra_instructions: str = Field(default="", max_length=4000)


class ReviewIn(BaseModel):
    action: str = Field(description="approve / revise / reject", pattern="^(approve|revise|reject)$")
    note: str = Field(default="", max_length=2000)
    final_text: str = Field(default="", max_length=100000)


class BriefingOut(BaseModel):
    id: int
    kind: str
    title: str
    department: str
    pushed: bool
    push_mode: str
    jdy_entry_ids: list = []
    created_at: datetime
    pushed_at: Optional[datetime] = None
    model_config = {"from_attributes": True}

    _v_lists = field_validator("jdy_entry_ids", mode="before")(_none_to_list)


# ---------- 智能对话模块（类 DeepSeek Harness） ----------

class ChatSessionCreateIn(BaseModel):
    title: str = Field(default="", max_length=128)
    model: str = Field(default="", max_length=32)  # 空=按场景默认/推荐
    scenario_id: Optional[int] = None              # 联动场景广场：场景提示词作为 system prompt
    privacy: str = Field(default="standard", pattern="^(standard|metadata_only)$")


class ChatMessageIn(BaseModel):
    content: str = Field(default="", max_length=20000)
    model: Optional[str] = Field(default=None, max_length=32)  # 本轮临时换模型；空=用会话默认
    attachment_ids: list[int] = Field(default_factory=list, max_length=5)


class ChatSessionPatchIn(BaseModel):
    title: Optional[str] = Field(default=None, max_length=128)
    model: Optional[str] = Field(default=None, max_length=32)
    status: Optional[str] = Field(default=None, pattern="^(open|closed)$")  # 可关不可删


class AttachmentOut(BaseModel):
    id: int
    session_id: Optional[int] = None
    filename: str
    ext: str
    size_bytes: int
    mime: str = ""
    extract_status: str = "ok"
    note: str = ""
    text_len: int = 0
    excerpt: str = ""
    created_at: datetime
    model_config = {"from_attributes": True}


class ChatSessionListItem(BaseModel):
    id: int
    title: str
    model: str
    status: str
    scenario_id: Optional[int] = None
    scenario_title: str = ""
    privacy: str = "standard"
    message_count: int = 0
    last_message: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
