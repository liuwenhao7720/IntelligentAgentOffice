# -*- coding: utf-8 -*-
"""成熟规则执行引擎：Prompt 已验证 → 自动成稿 → 人工审核修改放行。

规则分级：
- draft       探索中，可自由生成
- validated   已验证，建议沿用（默认人工改稿后发出）
- production  成熟规则：系统自动成稿，强制人工审核放行后才能对外/入库
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..database import Scenario, SessionMessage, ChatSession
from ..services.model_gateway import gateway
from ..services.prompt_builder import build_messages


# 成熟规则种子（内容依据：《项目部方案设计Prompt》《工程技术部前期预算方案（已验证沿用）》）
MATURE_RULES: list[dict] = [
    {
        "code": "SC-PRJ-101",
        "title": "投标方案自动生成（项目部成熟规则）",
        "department": "项目部",
        "category": "project",
        "maturity": "production",
        "roles": "项目工程师 / 项目部经理（审核放行）",
        "timing": "标书/询价进入后，按阶段自动生成方案包，人工审核后放行",
        "goal": "依据《项目部方案设计Prompt》成熟规则自动成稿；人工审核修改放行后方可对外",
        "default_model": "kimi",
        "fallback_model": "deepseek",
        "quality_notes": "十二条铁律必须遵守；缺信息显式假设；禁伪造业绩/图纸；经理审核放行",
        "kpi_links": [
            {"code": "KPI-PRJ-01", "name": "项目按时完成率", "weight": "27%", "dimension": "V-价值创造", "source": "简道云[项目管理→投标管理]"},
            {"code": "KPI-PRJ-04", "name": "中标率", "weight": "5%", "dimension": "V-价值创造", "source": "简道云[CRM-商机管理]"},
            {"code": "KPI-PRJ-03", "name": "工作完成质量(AI)", "weight": "16%", "dimension": "L-连接协同", "source": "简道云[任务管理-AI评分]"},
        ],
        "variables": [
            {"key": "project_name", "label": "项目名称", "required": True, "placeholder": ""},
            {"key": "bidder", "label": "投标主体", "required": True, "placeholder": "V-FLO Pumps & Systems Co., Ltd."},
            {"key": "stage", "label": "执行阶段", "required": True, "placeholder": "G1标书分析 / G2技术方案 / G3图纸 / G4校核 / G5成本 / G6投标包"},
            {"key": "source_folder", "label": "标书资料文件夹", "required": True, "placeholder": "任务项目文件夹路径"},
            {"key": "key_requirements", "label": "关键要求/补充说明", "required": False, "placeholder": ""},
        ],
        "prompt_template": (
            "你是 V-FLO Pumps & Systems Co., Ltd. 投标方案首席工程师团队"
            "（同时扮演工艺、机械、控制、造价、标书专员、项目经理）。\n"
            "现在执行：{{stage}} 阶段任务。投标主体：{{bidder}}。项目：{{project_name}}。\n"
            "资料文件夹：{{source_folder}}\n补充：{{key_requirements}}\n\n"
            "请先复述本阶段的输入、输出、验收标准，确认无遗漏后再开始执行。\n\n"
            "【全局十二条铁律（必须遵守）】\n"
            "1) 单一数据源：《设备与材料总表》为唯一数据基准，矛盾处显式报告。\n"
            "2) 缺失信息显式化：标书未明示处标注「⚠️标书未明示，本方案按××假设取值」，禁止编造精确值。\n"
            "3) 关键数值双源核验；无法确认标「⚠️待核实」。\n"
            "4) 标准等同映射：ISO/API/EN/ANSI 等给出 GB 等同映射表。\n"
            "5) 三遍成稿：骨架→血肉→精修，禁止一次输出万字。\n"
            "6) 深度量化：设备描述不少于八要素（原理结构、关键部件、性能参数表、材质、外形重量、"
            "选型依据、执行标准、检验要求）。\n"
            "7) 编号体系统一（位号/文件号/图号/表号）。\n"
            "8) 文件管理：01_标书分析…07_竞品对标 七目录；文件名「编号-名称-版本」。\n"
            "9) 过程可追溯：计算保留公式与代入；报价保留单价×数量+费率。\n"
            "10) 完成即自检，未通过项修复后交付。\n"
            "11) 图片图纸合规：A类AI生成/B类公开案例/C类自有业绩，强制性质标注；"
            "严禁伪造业绩、证书、检测报告；自有业绩无照片时用占位框「待填入真实数据」。\n"
            "12) 图文入正文：图片须嵌入对应章节，含图号、图题、图注、说明文字。\n\n"
            "输出要求：结论先行、工程语体；中文为主，型号/标准号/单位保留原文。\n"
            "本阶段产出仅为【草稿】，必须标注「待项目经理审核放行」后方可对外。"
        ),
        "security_level": "normal",
    },
    {
        "code": "SC-ENG-101",
        "title": "预算方案设计（工程技术部前期·已验证沿用）",
        "department": "工程技术部（前期）",
        "category": "dev",
        "maturity": "validated",
        "roles": "工程技术部主管 / 组长 / 经理（审核）",
        "timing": "询价成本核算与预算方案编制时（已验证 Prompt，继续沿用）",
        "goal": "沿用已验证预算方案设计 Prompt：自动成稿 + 人工审核修改放行",
        "default_model": "deepseek",
        "fallback_model": "kimi",
        "quality_notes": "成本结构完整、单价来源可追溯、与设备总表一致；主管审核后放行",
        "kpi_links": [
            {"code": "KPI-ENG-DOC", "name": "文档记录完整度", "weight": "7-10%", "dimension": "O-优化创新", "source": "简道云[内部资料]"},
            {"code": "KPI-ENG-ONLINE", "name": "项目按时完成率", "weight": "15-18%", "dimension": "V-价值创造", "source": "简道云[项目管理]"},
        ],
        "variables": [
            {"key": "project_name", "label": "项目名称", "required": True, "placeholder": ""},
            {"key": "scope", "label": "报价范围与配置", "required": True, "placeholder": "主机/辅机/备件/服务"},
            {"key": "bom_raw", "label": "BOM/设备清单要点", "required": True, "placeholder": "位号、名称、数量、材质"},
            {"key": "price_basis", "label": "单价依据", "required": True, "placeholder": "历史价/供应商报价/样本价"},
            {"key": "target_margin", "label": "目标毛利", "required": False, "placeholder": "如 18%"},
            {"key": "assumptions", "label": "假设与风险", "required": False, "placeholder": "汇率、运保费、税率等"},
        ],
        "prompt_template": (
            "你是 V-FLO 工程技术部（前期）预算方案团队，执行已验证的"
            "《工程技术部（前期）预算方案设计Prompt（V3.0）》规则（继续沿用）。\n"
            "项目：{{project_name}}\n范围：{{scope}}\n"
            "BOM 要点：{{bom_raw}}\n单价依据：{{price_basis}}\n"
            "目标毛利：{{target_margin}}\n假设与风险：{{assumptions}}\n\n"
            "【V3.0 强制红线（全文适用）】\n"
            "1) 输出保存到客户询价文件夹同级工作区，禁止散落。\n"
            "2) 禁止臆造：参数/认证/数字必须来自客户文件、V-FLO 规范、标准或显式假设。\n"
            "3) 禁止跳项：任何位号与客户明示要求必须解析、记录、评估。\n"
            "4) 禁止断链：结论可回溯（文件名+页码/Sheet+章节/单元格+原文摘录）。\n\n"
            "【沿用规则要点】\n"
            "- 需求解析→需求分析→技术方案→模板填写→商务报价→应答→尺寸重量→竞品对比 全链路；\n"
            "- 双报告：报告一（选型参数导入表，严格模板映射）+ 报告二（15 项核心要求解析与合规评估）；\n"
            "- 合规四态 COMPLIANT / NON_COMPLIANT / CONDITIONAL / UNKNOWN + 风险四级；\n"
            "- 证据链：每条提取含来源定位+原文摘录+置信度；置信度<0.70 进人工复核；\n"
            "- 位号主数据表（TMD）唯一数据源，后续阶段只读引用；\n"
            "- 成本分项保留「单价×数量+费率」；认证/第三方检验/NDT/特殊材质等按触发条件计提增项；\n"
            "- 高/中/低三档预算 + 敏感项 Top5；汇率运费税费单列敏感分析。\n\n"
            "输出含：封面（编制/审核栏）、编制说明、费用汇总、分项明细、合规与偏差表、敏感分析、结论建议。\n"
            "标注：【预算草稿 · 待主管审核放行】。未经审核不得作为对外报价依据。"
        ),
        "security_level": "normal",
    },
]


def seed_mature_rules(db: Session) -> int:
    """把成熟规则写入场景库（production/validated/draft）。"""
    from ..seed.scenarios import _usage, WORKFLOW_MAP  # noqa: F401
    from ..seed.mature_rules_dept import DEPT_RULES
    created = 0
    for item in list(MATURE_RULES) + list(DEPT_RULES):
        exists = db.query(Scenario).filter(Scenario.code == item["code"]).first()
        payload = dict(
            title=item["title"],
            department=item["department"],
            category=item["category"],
            roles=item["roles"],
            timing=item["timing"],
            goal=item["goal"],
            prompt_template=item["prompt_template"],
            variables=item["variables"],
            default_model=item["default_model"],
            fallback_model=item["fallback_model"],
            quality_notes=item["quality_notes"],
            kpi_links=item["kpi_links"],
            security_level=item["security_level"],
            status="active",
            version="1.0",
            author="成熟规则库",
            maturity=item["maturity"],
            usage_steps=(
                "①资料文件夹 ②Mimo V2.6 新建项目 ③选择成熟规则自动成稿 ④人工审核修改 ⑤审核放行后发出/归档"
            ),
            workflow_stage="成熟规则-自动成稿→人工放行",
        )
        if exists:
            for k, v in payload.items():
                setattr(exists, k, v)
        else:
            db.add(Scenario(code=item["code"], **payload))
            created += 1
    db.commit()
    return created


@dataclass
class ReviewDecision:
    action: str  # approve / revise / reject
    note: str = ""


def generate_with_review(
    db: Session,
    user,
    scenario: Scenario,
    variables: dict,
    model: Optional[str] = None,
    extra_instructions: str = "",
) -> dict:
    """成熟规则生成：产出草稿 + 审核状态字段。

    maturity=production：必须走人工审核放行，结果标记 awaiting_review。
    maturity=validated：自动成稿，标记 draft（沿用规则，仍建议审核）。
    maturity 其他/空：与普通场景一致。
    """
    messages = build_messages(scenario.prompt_template, variables, extra_instructions=extra_instructions)
    m = model or scenario.default_model
    result = gateway.chat(messages, model=m)

    maturity = getattr(scenario, "maturity", "") or "draft"
    if maturity == "production":
        review_status = "awaiting_review"
        banner = (
            "\n\n【审核状态】awaiting_review（成熟规则·强制人工审核）\n"
            "本稿由已验证 Prompt 自动生成。须经项目经理/授权人审核修改并点击「审核放行」后，"
            "方可对外发送或写入简道云。未放行 = 不得发出。\n"
        )
    elif maturity == "validated":
        review_status = "draft"
        banner = (
            "\n\n【审核状态】draft（已验证规则·建议审核）\n"
            "本稿由已验证规则生成，可直接修改使用；对外正式文件建议主管审核。\n"
        )
    else:
        review_status = "auto"
        banner = ""

    text = result.text + banner

    session = ChatSession(
        user_id=user.id,
        scenario_id=scenario.id,
        title=f"[{scenario.code}] {scenario.title}",
        model=m,
        variables=variables,
        review_status=review_status if review_status != "auto" else "",
    )
    db.add(session)
    db.flush()
    msg = SessionMessage(
        session_id=session.id,
        role="assistant",
        content=text,
        model=f"{result.provider}:{result.model}",
        is_final=False,
    )
    db.add(msg)
    scenario.use_count = (scenario.use_count or 0) + 1
    db.commit()
    db.refresh(session)

    return {
        "session_id": session.id,
        "scenario_code": scenario.code,
        "maturity": maturity,
        "review_status": review_status,
        "text": text,
        "model": result.model,
        "provider": result.provider,
        "review_required": maturity == "production",
    }


class ReviewForbidden(Exception):
    """审核权限不足（自审自放或非授权角色）。"""


def apply_review(db: Session, user, session_id: int, decision: ReviewDecision, final_text: str = "") -> dict:
    """人工审核放行 / 退回修改 / 否决。

    权限规则（附件5 §8.3「经理/授权人放行」，用户确认的口径）：
    - admin（管理层/授权人）可放行一切；
    - staff 可审核放行「他人」的稿子；
    - 任何人不得审核放行自己生成的稿子（自审自放 → 403）。
    """
    from ..database import EditDiff
    from ..services.prompt_builder import diff_stats

    session = db.query(ChatSession).get(session_id)
    if not session:
        raise ValueError("会话不存在")
    if session.user_id == user.id:
        raise ReviewForbidden("不能审核放行自己生成的稿子，请提交经理/授权人审核")

    ai = next((m for m in reversed(session.messages) if m.role == "assistant"), None)
    ai_text = ai.content if ai else ""
    summary, ratio = diff_stats(ai_text, final_text or ai_text)

    note = f"审核人：{user.name} | {decision.action} | {decision.note}"

    db.add(SessionMessage(
        session_id=session.id,
        role="assistant",
        content=(final_text or ai_text) + f"\n\n【审核结论】{note}",
        model="human-review",
        is_final=decision.action == "approve",
    ))
    if final_text:
        db.add(EditDiff(
            session_id=session.id,
            field="content",
            ai_text=ai_text,
            final_text=final_text,
            diff_summary=summary,
            edit_ratio=ratio,
        ))

    # 结构化审核留痕（附件1 §2.1 G5：审批记录；附件5 §8.3 放行留痕）
    review_map = {"approve": "approved", "revise": "revising", "reject": "rejected"}
    session.review_status = review_map.get(decision.action, session.review_status)
    session.reviewed_by = user.name
    session.review_note = decision.note or ""
    session.reviewed_at = datetime.utcnow()
    if decision.action == "approve":
        session.status = "done"
    db.commit()
    return {
        "session_id": session.id,
        "review_status": session.review_status,
        "action": decision.action,
        "diff_summary": summary,
        "edit_ratio": ratio,
        "note": note,
    }
