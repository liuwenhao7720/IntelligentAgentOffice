# -*- coding: utf-8 -*-
"""T02 数据层：SQLAlchemy 1.4 模型（开发 SQLite，生产切 PostgreSQL）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from .config import get_settings

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    wecom_userid = Column(String(64), unique=True, index=True)
    name = Column(String(64))
    department = Column(String(64), default="")
    position = Column(String(64), default="")
    role = Column(String(32), default="staff")  # staff / admin
    created_at = Column(DateTime, default=datetime.utcnow)


class Scenario(Base):
    """场景卡 = 公司提示词资产。"""
    __tablename__ = "scenarios"
    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, index=True)
    title = Column(String(128))
    department = Column(String(64), index=True)
    roles = Column(String(128), default="")
    timing = Column(String(128), default="")
    goal = Column(Text, default="")
    category = Column(String(32), default="general")
    prompt_template = Column(Text)
    variables = Column(JSON, default=list)
    default_model = Column(String(32), default="mimo")
    fallback_model = Column(String(32), default="deepseek")
    output_format = Column(String(64), default="markdown")
    quality_notes = Column(Text, default="")
    example_input = Column(Text, default="")
    example_output = Column(Text, default="")
    version = Column(String(16), default="1.0")
    status = Column(String(16), default="active")
    author = Column(String(64), default="system")
    use_count = Column(Integer, default=0)
    # 关联简道云 KPI：[{code,name,weight,dimension,source}]  V/F/L/O 四维
    kpi_links = Column(JSON, default=list)
    # normal / export_control / sensitive（出口管制场景强制合规审查）
    security_level = Column(String(16), default="normal")
    # 工作流节点与使用步骤（T13 岗位工作流矩阵）
    workflow_stage = Column(String(64), default="")
    usage_steps = Column(String(256), default="")
    # 成熟规则分级：draft / validated / production
    maturity = Column(String(16), default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True)
    title = Column(String(128), default="")
    model = Column(String(32), default="mimo")
    status = Column(String(16), default="open")
    variables = Column(JSON, default=dict)
    rating = Column(Integer, nullable=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    messages = relationship("SessionMessage", back_populates="session", cascade="all, delete-orphan")


class SessionMessage(Base):
    __tablename__ = "session_messages"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), index=True)
    role = Column(String(16))
    content = Column(Text)
    model = Column(String(32), default="")
    is_final = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    session = relationship("ChatSession", back_populates="messages")


class EditDiff(Base):
    """人改 AI 的 diff —— 数字资产核心。"""
    __tablename__ = "edit_diffs"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), index=True)
    field = Column(String(64), default="content")
    ai_text = Column(Text)
    final_text = Column(Text)
    diff_summary = Column(Text, default="")
    edit_ratio = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    title = Column(String(128))
    content = Column(Text)
    department = Column(String(64), default="")
    visibility = Column(String(16), default="dept")
    tags = Column(JSON, default=list)
    featured = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    action = Column(String(64))
    resource = Column(String(64), default="")
    detail = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class TaskProject(Base):
    """任务项目：每项工作的原子单位。
    标准开工：资料文件夹 → Mimo V2.6 新建项目 → 场景卡工作流推进。
    """
    __tablename__ = "task_projects"
    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, index=True)  # TP-20260927-001
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String(128))
    department = Column(String(64), default="")
    position = Column(String(64), default="")
    # 开工输入
    folder_path = Column(String(256), default="")  # 资料文件夹（本机/网盘路径）
    folder_name = Column(String(128), default="")
    materials = Column(JSON, default=list)  # [{name, type, note}]
    # Mimo V2.6 项目绑定
    mimo_project = Column(String(128), default="")  # Mimo 中的项目名/ID
    mimo_ready = Column(Integer, default=0)  # 0未建 1已建
    # 工作流
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True)
    workflow_stage = Column(String(64), default="")
    status = Column(String(16), default="created")  # created/materials_ready/mimo_ready/running/done/archived
    progress = Column(JSON, default=list)  # [{step, status, note, at}]
    outputs = Column(JSON, default=list)  # 产出物
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskItem(Base):
    """任务池（简道云镜像 + AI 扩展字段，见《任务管理智能体落地实施方案》3.3）。"""
    __tablename__ = "task_items"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    external_task_no = Column(String(64), default="")
    title = Column(String(256))
    description = Column(Text, default="")
    project_name = Column(String(128), default="")
    status = Column(String(32), default="待办")
    start_time = Column(String(32), default="")
    due_time = Column(String(32), default="")
    estimated_hours = Column(Float, default=1.0)
    priority = Column(String(16), default="中")
    source = Column(String(32), default="manual")
    ai_source_type = Column(String(32), default="new_input")
    ai_urgency = Column(Integer, default=3)
    ai_importance = Column(Integer, default=3)
    ai_value = Column(String(16), default="中")
    ai_impact_scope = Column(String(16), default="个人")
    ai_complexity = Column(Integer, default=3)
    ai_dependency_ids = Column(JSON, default=list)
    ai_fixed_start = Column(String(32), default="")
    ai_fixed_end = Column(String(32), default="")
    ai_priority_score = Column(Float, default=0.0)
    ai_schedule_block = Column(JSON, default=dict)
    ai_remind_policy = Column(JSON, default=dict)
    ai_dedup_key = Column(String(64), default="", index=True)
    ai_confidence = Column(Float, default=0.5)
    ai_user_feedback = Column(JSON, default=dict)
    ai_leader_assigned = Column(Boolean, default=False)
    ai_blocking_others = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExportCheck(Base):
    """V-FLO 出口管制合规审查单（执行留痕，不可删改历史）。"""
    __tablename__ = "export_checks"
    id = Column(Integer, primary_key=True)
    case_no = Column(String(32), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    customer_name = Column(String(128), default="")
    country = Column(String(64), default="")
    end_user = Column(String(128), default="")
    end_use = Column(String(256), default="")
    product_desc = Column(String(256), default="")
    hs_code = Column(String(32), default="")
    country_risk = Column(String(16), default="unknown")   # low/medium/high/blocked
    sanctions_hit = Column(String(16), default="none")      # none/possible/confirmed
    item_control = Column(String(16), default="unknown")    # EAR99/controlled/dual_use/unknown
    license_needed = Column(String(16), default="unknown")  # yes/no/unknown
    red_flags = Column(JSON, default=list)
    decision = Column(String(16), default="pending")        # pass/reject/escalate/pending
    decision_note = Column(Text, default="")
    checklist = Column(JSON, default=list)
    attachments = Column(JSON, default=list)
    reviewed_by = Column(String(64), default="")
    status = Column(String(16), default="draft")            # draft/submitted/approved/rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


_settings = get_settings()
_is_sqlite = _settings.database_url.startswith("sqlite")
_engine_kwargs = {
    "connect_args": {"check_same_thread": False} if _is_sqlite else {},
    "future": True,
    "pool_pre_ping": True,
}
# SQLite 用 NullPool，不接受 pool_size/max_overflow
if not _is_sqlite:
    _engine_kwargs.update({
        "pool_size": _settings.db_pool_size,
        "max_overflow": _settings.db_max_overflow,
        "pool_recycle": _settings.db_pool_recycle,
    })
_engine = create_engine(_settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(_engine)


def ping_db() -> bool:
    """健康检查用：探测数据库连通性。"""
    try:
        with _engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
