# -*- coding: utf-8 -*-
"""T02 数据层：SQLAlchemy 1.4 模型（开发 SQLite，生产切 PostgreSQL）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, create_engine,
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
    role = Column(String(32), default="staff")  # staff / manager / compliance / admin（auth.ROLE_PERMS）
    # 账号状态：active / disabled（停用即登录隔离，token 每请求查库即时生效）
    status = Column(String(16), default="active")
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
    # 附件3 §3.4：留痕可关不可删 —— standard / metadata_only（仅元数据留痕）
    privacy = Column(String(16), default="standard")
    # 成熟规则审核放行（附件5 §8.3）：awaiting_review/approved/revising/rejected/""
    review_status = Column(String(16), default="")
    reviewed_by = Column(String(64), default="")
    review_note = Column(Text, default="")
    reviewed_at = Column(DateTime, nullable=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    # 来源频道：workbench（工作台，存量默认）/ chat（智能对话模块）
    channel = Column(String(16), default="workbench")
    # 所属任务项目（工作台合规闸口：生成时读取该项目的合规审查结果，不重复审查）
    task_project_code = Column(String(32), default="", index=True)
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


class ChatAttachment(Base):
    """智能对话模块的上传附件：文件留存 + 解析文本（注入对话上下文）。

    留痕规则（与会话一致：可关不可删）：
    - 未绑定会话（session_id 为空）的附件允许删除（用户传错了可撤回）；
    - 一旦随消息绑定会话即不可删，作为留痕的一部分保留。
    """
    __tablename__ = "chat_attachments"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=True, index=True)
    filename = Column(String(256))            # 原始文件名（仅展示用）
    ext = Column(String(16), default="")      # 小写扩展名（不含点）
    size_bytes = Column(Integer, default=0)
    storage_path = Column(String(512))        # 服务端存储路径（uuid.ext）
    mime = Column(String(128), default="")
    extracted_text = Column(Text, default="")  # 解析出的文本（注入上下文用）
    extract_status = Column(String(16), default="ok")  # ok / failed / unsupported
    note = Column(String(256), default="")     # 解析备注（如"扫描件无文本"）
    created_at = Column(DateTime, default=datetime.utcnow)


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
    distributed_to = Column(JSON, default=list)  # 附件3 §3.1：归档与分发记录（发到哪个群/目录）
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
    # 项目初步分析要素（合规审查前移：立项/初步分析阶段完成审查，工作台只调用结果）
    customer_name = Column(String(128), default="")   # 客户名称（涉外项目必填）
    country = Column(String(64), default="")          # 目的地/签约国
    export_check_case_no = Column(String(32), default="")  # 绑定的合规审查单号（初步分析阶段产出）
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
    # 今日工作安排三态标记（手册 1.5：B0 固定会议 / 他人要求 / 今日固定）
    is_meeting = Column(Boolean, default=False)
    is_other_request = Column(Boolean, default=False)
    is_today_fixed = Column(Boolean, default=False)
    # 简道云数据 ID（同步来源行，用于状态回写；空=本地任务）
    jdy_data_id = Column(String(64), default="", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Briefing(Base):
    """简道云自动化文稿（早宣/晚总/周计划/周总结/项目结项）落库。

    附件5 §8.5：部门经理需要按部门查看早宣/晚总推送量与问题清单，
    因此生成与推送都必须持久化（含推送回执 entry_id）。
    """
    __tablename__ = "briefings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    department = Column(String(64), default="", index=True)
    kind = Column(String(32), index=True)       # morning/evening/weekly_plan/weekly_summary/project_closure
    title = Column(String(256), default="")
    content = Column(Text, default="")
    wecom_card = Column(Text, default="")
    jdy_payload = Column(JSON, default=dict)    # 汇总 payload
    jdy_tasks = Column(JSON, default=list)      # 解析出的逐条任务 payload
    pushed = Column(Boolean, default=False)
    push_mode = Column(String(16), default="")  # mock/live
    jdy_entry_ids = Column(JSON, default=list)  # 推送回执
    pushed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class JdyRecord(Base):
    """简道云表单数据本地镜像（单向：简道云 → 本项目；v-crm 镜像模式的通用表实现）。

    raw 结构：{"_fields": {widget_id: 原始值}, "_labels": {widget_id: 字段中文名}}
    —— 记录自描述标签，前端无需预知表单结构即可友好展示。
    """
    __tablename__ = "jdy_records"
    __table_args__ = (UniqueConstraint("entry_id", "data_id", name="uq_jdy_record"),)
    id = Column(Integer, primary_key=True)
    entry_id = Column(String(64), index=True)
    data_id = Column(String(64))
    kind = Column(String(32), index=True)          # task / knowledge（对应已配置表单）
    # 投影列（列表/搜索用；取不到的字段留空，raw 里仍有原文）
    title = Column(String(256), default="", index=True)
    status = Column(String(32), default="")
    owner = Column(String(128), default="")
    dept = Column(String(64), default="")
    due_time = Column(String(32), default="")
    submit_time = Column(String(32), default="")
    raw = Column(JSON, default=dict)
    synced_at = Column(DateTime, default=datetime.utcnow)


class JdySyncLog(Base):
    """简道云拉取同步留痕（对齐 v-crm SyncLog 语义）。"""
    __tablename__ = "jdy_sync_logs"
    id = Column(Integer, primary_key=True)
    scope = Column(String(64), default="")          # task / knowledge / full
    status = Column(String(16), default="success")  # success / failed / skipped
    message = Column(String(512), default="")
    items = Column(Integer, default=0)              # 本轮镜像记录数
    created_n = Column(Integer, default=0)
    updated_n = Column(Integer, default=0)
    pruned_n = Column(Integer, default=0)
    truncated = Column(Boolean, default=False)      # 拉取被 max_pages 截断（本轮跳过 prune）
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ComplianceRule(Base):
    """合规审查规则与资料资产（可调用配置，附件：合规审查规则与资料配置）。

    category：
    - country_list   国家名单（value.codes=[]；code=western/watch/normal_coop）
    - item_hints     物项提示词表（value.words=[]；code=nuclear/chembio/missile/military/industrial/process）
    - end_use_redline 最终用途红线关键词（value.words=[]；code=wmd/military）
    - red_flag       红旗规则（value.trigger/desc）
    - checklist      检查清单项（value.required=bool）
    - decision_note  决策规则文案（value.text；code=reject_wmd/escalate_dual_use/...）
    - resource       资料资产：审查规则文件/选型软件/模板等
                     （value={type: 软件|文档|网址|模板, link, applicable, version}）
    """
    __tablename__ = "compliance_rules"
    __table_args__ = (UniqueConstraint("category", "code", name="uq_compliance_rule"),)
    id = Column(Integer, primary_key=True)
    category = Column(String(32), index=True)
    code = Column(String(64))
    name = Column(String(256), default="")
    value = Column(JSON, default=dict)
    description = Column(String(512), default="")
    enabled = Column(Boolean, default=True)
    sort = Column(Integer, default=0)
    updated_by = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExportCheck(Base):
    """V-FLO 出口管制合规审查单（执行留痕，不可删改历史）。"""
    __tablename__ = "export_checks"
    id = Column(Integer, primary_key=True)
    case_no = Column(String(32), unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    customer_name = Column(String(128), default="")
    middleman = Column(String(128), default="")          # 中间商（EXP-01 链条识别）
    country = Column(String(64), default="")             # 目的地/签约国
    arrival_country = Column(String(64), default="")     # 运抵国（EXP-03）
    end_user_country = Column(String(64), default="")    # 最终用户所在国（EXP-03）
    end_user = Column(String(128), default="")
    end_use = Column(String(256), default="")
    product_desc = Column(String(256), default="")
    hs_code = Column(String(32), default="")
    country_risk = Column(String(16), default="unknown")   # low/medium/high/blocked
    sanctions_hit = Column(String(16), default="none")      # none/possible/confirmed
    item_control = Column(String(16), default="unknown")    # EAR99/controlled/dual_use/unknown
    license_needed = Column(String(16), default="unknown")  # yes/no/unknown
    red_flags = Column(JSON, default=list)
    decision = Column(String(16), default="pending")        # pending/manual_review/escalate/reject/pass（附件1 §2.4）
    decision_note = Column(Text, default="")
    checklist = Column(JSON, default=list)
    attachments = Column(JSON, default=list)
    reviewed_by = Column(String(64), default="")
    review_note = Column(Text, default="")
    reviewed_at = Column(DateTime, nullable=True)
    # 审查前移：审查单所属任务项目（项目初步分析阶段完成审查的凭据）
    task_project_code = Column(String(32), default="", index=True)
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


def _table_columns(insp, table: str) -> set:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:  # noqa: BLE001
        return set()


def migrate_db() -> None:
    """轻量迁移：为已存在的表补充新增列（create_all 不会 ALTER）。

    幂等 + 多 worker 并发安全：
    - 按 inspect 检查后再 ADD COLUMN；
    - 并发 ALTER 时另一进程可能已抢先加列（PG: DuplicateColumn / SQLite: duplicate column），
      捕获后跳过即可（列已存在即目标状态）。
    """
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import OperationalError, ProgrammingError

    insp = inspect(_engine)
    bool_default = "FALSE" if _engine.dialect.name == "postgresql" else "0"
    json_default = "'{}'" if _engine.dialect.name == "postgresql" else "'{}'"
    # 表 -> [(列名, DDL 类型后缀)]（附件4 门禁1：结构变更必须有迁移路径）
    plan = {
        "task_items": [
            ("is_meeting", f"BOOLEAN DEFAULT {bool_default}"),
            ("is_other_request", f"BOOLEAN DEFAULT {bool_default}"),
            ("is_today_fixed", f"BOOLEAN DEFAULT {bool_default}"),
            ("jdy_data_id", "VARCHAR(64) DEFAULT ''"),
        ],
        "task_projects": [
            ("customer_name", "VARCHAR(128) DEFAULT ''"),
            ("country", "VARCHAR(64) DEFAULT ''"),
            ("export_check_case_no", "VARCHAR(32) DEFAULT ''"),
        ],
        "chat_sessions": [
            ("privacy", "VARCHAR(16) DEFAULT 'standard'"),
            ("review_status", "VARCHAR(16) DEFAULT ''"),
            ("reviewed_by", "VARCHAR(64) DEFAULT ''"),
            ("review_note", "TEXT DEFAULT ''"),
            ("reviewed_at", "TIMESTAMP NULL"),
            ("channel", "VARCHAR(16) DEFAULT 'workbench'"),
            ("task_project_code", "VARCHAR(32) DEFAULT ''"),
        ],
        "export_checks": [
            ("middleman", "VARCHAR(128) DEFAULT ''"),
            ("arrival_country", "VARCHAR(64) DEFAULT ''"),
            ("end_user_country", "VARCHAR(64) DEFAULT ''"),
            ("review_note", "TEXT DEFAULT ''"),
            ("reviewed_at", "TIMESTAMP NULL"),
            ("task_project_code", "VARCHAR(32) DEFAULT ''"),
        ],
        "users": [
            ("status", "VARCHAR(16) DEFAULT 'active'"),
        ],
        "assets": [
            ("distributed_to", "JSON"),
        ],
        "scenarios": [
            ("kpi_links", "JSON"),
            ("security_level", "VARCHAR(16) DEFAULT 'normal'"),
            ("workflow_stage", "VARCHAR(64) DEFAULT ''"),
            ("usage_steps", "VARCHAR(256) DEFAULT ''"),
            ("maturity", "VARCHAR(16) DEFAULT 'draft'"),
        ],
    }
    for table, columns in plan.items():
        if table not in insp.get_table_names():
            continue
        existing = _table_columns(insp, table)
        for col, ddl in columns:
            if col in existing:
                continue
            try:
                with _engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                print(f"[migrate] {table} +{col}")
            except (ProgrammingError, OperationalError) as e:
                # 并发 worker 已加列（DuplicateColumn / duplicate column name）→ 视为成功
                msg = str(e).lower()
                if "already exists" in msg or "duplicate column" in msg or "duplicate_column" in msg:
                    continue
                raise


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
