# -*- coding: utf-8 -*-
"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DevLoginIn(BaseModel):
    name: str = "演示员工"
    department: str = "项目事业部"
    position: str = "项目经理"
    role: str = "staff"


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
    use_count: int
    kpi_links: list = []
    security_level: str = "normal"
    workflow_stage: str = ""
    usage_steps: str = ""
    maturity: str = "draft"
    model_config = {"from_attributes": True}


class ScenarioDetailOut(ScenarioOut):
    prompt_template: str


class SessionCreate(BaseModel):
    scenario_id: Optional[int] = None
    title: str = ""
    model: str = "mimo"
    variables: dict = Field(default_factory=dict)


class GenerateIn(BaseModel):
    model: Optional[str] = None
    extra_instructions: str = ""
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
    tokens_in: int
    tokens_out: int
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)
    model_config = {"from_attributes": True}


class FinalizeIn(BaseModel):
    content: str = Field(description="人工定稿内容")


class RatingIn(BaseModel):
    rating: int = Field(ge=1, le=5)


class AssetCreate(BaseModel):
    session_id: Optional[int] = None
    title: str
    content: str
    visibility: str = "dept"
    tags: list[str] = Field(default_factory=list)


class AssetOut(BaseModel):
    id: int
    title: str
    content: str
    department: str
    visibility: str
    tags: list
    featured: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class ExportCheckIn(BaseModel):
    customer_name: str
    country: str
    end_user: str = ""
    end_use: str = ""
    product_desc: str = ""
    hs_code: str = ""
    extra_red_flags: list[str] = Field(default_factory=list)


class ExportCheckOut(BaseModel):
    id: int
    case_no: str
    customer_name: str
    country: str
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
    created_at: datetime
    model_config = {"from_attributes": True}


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


class MatureGenerateIn(BaseModel):
    variables: dict = Field(default_factory=dict)
    model: Optional[str] = None


class ReviewIn(BaseModel):
    action: str = Field(description="approve / revise / reject")
    note: str = ""
    final_text: str = ""
