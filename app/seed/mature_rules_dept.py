# -*- coding: utf-8 -*-
"""各部门成熟规则初稿（draft，供部门领导按实际修改后升 validated/production）。

模板结构（与 SC-PRJ-101 / SC-ENG-101 一致）：
角色立场 → 强制红线 → 执行规则 → 输入变量 → 输出结构 → 审核放行标注

升级路径：draft（本文件）→ 部门领导改定并试用 3 次 → validated → 补放行人 → production
"""
from __future__ import annotations

# 统一红线头（各部门通用）
_COMMON_RED = (
    "【强制红线（全文适用）】\n"
    "1) 禁止臆造：参数、日期、人名、金额、标准号必须来自输入或显式标注假设。\n"
    "2) 禁止跳项：输入中的每一项要求都必须被处理、记录或显式说明不适用。\n"
    "3) 禁止断链：关键结论标注来源（输入原文/数据/条款）。\n"
    "4) 本稿仅为草稿，文末必须标注「待{审核角色}审核放行」；未放行不得对外/入库。\n"
)


def _rule(
    code, title, department, category, roles, timing, goal,
    default_model, fallback_model, quality_notes, kpi_links,
    variables, prompt_template,
    maturity="draft",
):
    return {
        "code": code,
        "title": title,
        "department": department,
        "category": category,
        "maturity": maturity,
        "roles": roles,
        "timing": timing,
        "goal": goal,
        "default_model": default_model,
        "fallback_model": fallback_model,
        "quality_notes": quality_notes,
        "kpi_links": kpi_links,
        "variables": variables,
        "prompt_template": prompt_template,
        "security_level": "normal",
    }


DEPT_RULES: list[dict] = [
    # ================= 商务部 =================
    _rule(
        "SC-SAL-201", "项目跟单六块周报（商务部成熟规则初稿）",
        "商务部", "sales",
        "项目跟单主管 / 项目跟单；商务部经理（审核放行）",
        "每周项目会前；或客户/领导索要跟单状态时",
        "按「文件/生产/检验/收款/澄清/发货」六块自动成稿，经理审核后使用",
        "deepseek", "kimi",
        "六块齐全、逾期有责任人与动作、与简道云任务可对账",
        [
            {"code": "KPI-SAL-04", "name": "订单交付准时率", "weight": "7-18%", "dimension": "V-价值创造", "source": "简道云[销售订单/出库]"},
            {"code": "KPI-SAL-CLARIFY", "name": "澄清闭环及时率", "weight": "12%", "dimension": "F-流程效率", "source": "简道云[任务管理]"},
        ],
        [
            {"key": "project", "label": "项目/订单号", "required": True, "placeholder": ""},
            {"key": "customer", "label": "客户", "required": True, "placeholder": ""},
            {"key": "six_blocks", "label": "六块现状", "required": True,
             "placeholder": "文件|生产|检验|收款|澄清|发货：各写状态/完成度/卡点"},
            {"key": "due_date", "label": "约定交期", "required": True, "placeholder": ""},
            {"key": "risks", "label": "风险与需协调", "required": False, "placeholder": ""},
        ],
        "你是 V-FLO 商务部项目跟单主管助理，执行跟单六块周报成熟规则。\n"
        "项目/订单：{{project}}\n客户：{{customer}}\n约定交期：{{due_date}}\n"
        "六块现状：{{six_blocks}}\n风险：{{risks}}\n\n"
        "【执行规则】\n"
        "1) 必须按六块（文件、生产、检验、收款、澄清、发货）逐块输出：状态（绿/黄/红）、完成度%、"
        "本周动作、卡点、责任人、下一步、截止日。\n"
        "2) 交期倒排：对照 {{due_date}} 标出每块剩余缓冲天数；缓冲<7 天标红。\n"
        "3) 逾期/将逾期必须给「升级建议」（谁、何时、做什么）。\n"
        "4) 与简道云任务对账：列出建议录入的 3 条以内的任务（五要素）。\n"
        "5) 结论先行：总体能否按期交付，一句话。" + _COMMON_RED.format(审核角色="商务部经理"),
    ),
    _rule(
        "SC-SAL-202", "合同/协议商务条款初审（商务部成熟规则初稿）",
        "商务部", "sales",
        "商务部经理 / 副经理 / 国际销售主管（审核放行）",
        "销售合同、合作协议、代理协议定稿前（非法务意见）",
        "输出商务风险清单与修改建议，经理/法务复核后放行",
        "deepseek", "kimi",
        "付款/验收/违约/质保/争议/出口管制六块覆盖；不替代法务",
        [
            {"code": "KPI-SAL-REVIEW", "name": "商务条款审核质量", "weight": "15%", "dimension": "O-优化创新", "source": "简道云/评审记录"},
            {"code": "KPI-SAL-05", "name": "客户投诉次数", "weight": "7-10%", "dimension": "F-流程效率", "source": "简道云[跟进记录]"},
        ],
        [
            {"key": "clauses", "label": "条款文本", "required": True, "placeholder": "粘贴合同相关条款"},
            {"key": "deal_context", "label": "交易背景", "required": True,
             "placeholder": "客户国别、金额量级、付款方式、交期、是否涉外"},
        ],
        "你是 V-FLO 商务部合同初审助理（不提供法律意见）。\n"
        "背景：{{deal_context}}\n条款：\n{{clauses}}\n\n"
        "【执行规则】\n"
        "1) 按六块覆盖检查：付款条件、验收与质保、违约与罚则、交付与风险转移、"
        "争议解决与适用法、出口管制与制裁条款。\n"
        "2) 每条风险输出：条款摘录 | 风险等级(高/中/低) | 对我方影响 | 建议修改方向 | 建议表述。\n"
        "3) 涉外合同必须提示出口管制/最终用途条款是否缺失（呼应 SC-EXP-003）。\n"
        "4) 标明「本清单为商务初审，正式意见以法务/合规官为准」。" + _COMMON_RED.format(审核角色="商务部经理"),
    ),

    # ================= 质检部 =================
    _rule(
        "SC-QA-201", "8D质量问题报告（质检部成熟规则初稿）",
        "质检部", "general",
        "质检部部长 / 主管 / 机械工程师QA（审核放行）",
        "客户投诉、批量不合格、重大 NCR 时",
        "按 8D 框架自动成稿，质量负责人审核后对内/对客户",
        "deepseek", "kimi",
        "D1–D8 齐全；根因有验证；禁编造检测数据；纠正预防可跟踪",
        [
            {"code": "KPI-QA-01", "name": "质量合格率", "weight": "18-20%", "dimension": "V-价值创造", "source": "简道云[质量记录]"},
            {"code": "KPI-QA-03", "name": "客户投诉次数", "weight": "8%", "dimension": "F-流程效率", "source": "简道云[跟进记录]"},
        ],
        [
            {"key": "problem", "label": "问题描述", "required": True, "placeholder": "现象/数量/批次/发现环节"},
            {"key": "product", "label": "产品/订单", "required": True, "placeholder": ""},
            {"key": "containment", "label": "围堵措施", "required": False, "placeholder": "已隔离/返工/全检等"},
            {"key": "analysis", "label": "原因线索", "required": False, "placeholder": "人机料法环测"},
            {"key": "customer", "label": "是否客诉/客户名", "required": False, "placeholder": ""},
        ],
        "你是 V-FLO 质检部质量工程师，执行 8D 报告成熟规则。\n"
        "产品/订单：{{product}}\n问题：{{problem}}\n"
        "围堵：{{containment}}\n线索：{{analysis}}\n客诉：{{customer}}\n\n"
        "【执行规则】\n"
        "1) 输出完整 8D：D1 小组、D2 问题描述、D3 临时围堵、D4 根因（含验证方法）、"
        "D5 永久措施、D6 实施与验证、D7 预防再发、D8 关闭与团队认可。\n"
        "2) D4 根因必须区分「已证实/待证实」；无证据写「待验证」，禁止编造检测数值。\n"
        "3) D3/D5 须有责任人与完成日期。\n"
        "4) 涉及客诉时增加「对客户沟通要点」一节（口径一致、不推诿、不过度承诺）。" + _COMMON_RED.format(审核角色="质检部部长"),
    ),
    _rule(
        "SC-QA-202", "质量月报与改进立项（质检部成熟规则初稿）",
        "质检部", "general",
        "质检部部长 / 主管（审核放行）",
        "每月质量分析会前",
        "数据驱动月报 + 可立项的流程改进清单",
        "kimi", "deepseek",
        "帕累托清晰；改进项可进简道云「流程改进项目」",
        [
            {"code": "KPI-QA-IMP", "name": "流程改进项目数", "weight": "8-10%", "dimension": "O-优化创新", "source": "简道云[项目结项/意见箱]"},
            {"code": "KPI-QA-DOC", "name": "文档记录完整度", "weight": "10-15%", "dimension": "O-优化创新", "source": "简道云[内部资料]"},
        ],
        [
            {"key": "month", "label": "月份", "required": True, "placeholder": "2026-09"},
            {"key": "metrics", "label": "质量数据", "required": True,
             "placeholder": "合格率/不良/客诉/NCR/一次交检合格率等"},
            {"key": "focus", "label": "本月重点问题", "required": False, "placeholder": ""},
        ],
        "你是 V-FLO 质检部质量分析助理。\n月份：{{month}}\n数据：{{metrics}}\n重点：{{focus}}\n\n"
        "【执行规则】\n"
        "1) 输出：指标同比环比表、不良帕累托（Top5）、根因假设、改进项目建议（可立项 2–3 条）、"
        "下月目标。\n"
        "2) 改进建议必须含：问题、目标、措施、责任人、周期、验收标准——可直接录入简道云项目结项/流程改进。\n"
        "3) 数据缺失标「未提供」，不得用占位数冒充。" + _COMMON_RED.format(审核角色="质检部部长"),
    ),

    # ================= 工程技术部（后期） =================
    _rule(
        "SC-ENG-201", "交付文件清单与澄清计划（工程技术部后期成熟规则初稿）",
        "工程技术部（后期）", "dev",
        "后期经理 / 副经理 / 机械工程师-后期（审核放行）",
        "合同交接后 3 日内",
        "生成交付文件清单、提交计划与澄清关闭机制",
        "deepseek", "kimi",
        "清单可考核；澄清 3 工作日闭环；与客户文件要求逐条对应",
        [
            {"code": "KPI-ENG-FILE", "name": "技术文件编制数", "weight": "25-30%", "dimension": "V-价值创造", "source": "简道云[任务管理]"},
            {"code": "KPI-ENG-ONLINE", "name": "项目按时完成率", "weight": "30%", "dimension": "V-价值创造", "source": "简道云[项目管理]"},
        ],
        [
            {"key": "order", "label": "订单/项目", "required": True, "placeholder": ""},
            {"key": "req_docs", "label": "客户要求文件", "required": True,
             "placeholder": "数据表/GA/PID/手册/合格证等，逐条列出"},
            {"key": "milestones", "label": "关键节点", "required": True, "placeholder": "提交日/客户批复日/发运日"},
            {"key": "team", "label": "接口人", "required": False, "placeholder": ""},
        ],
        "你是 V-FLO 工程技术部后期交付工程师。\n订单：{{order}}\n"
        "客户要求文件：{{req_docs}}\n节点：{{milestones}}\n接口人：{{team}}\n\n"
        "【执行规则】\n"
        "1) 输出文件清单表：编号|文件名|类型|责任人|计划提交日|状态|客户批复状态。\n"
        "2) 逐条对应客户要求，标注「已覆盖/缺项/待确认」。\n"
        "3) 澄清规则：客户批复 3 个工作日内闭环回复；列澄清台账（问题|提交日|应答日|状态）。\n"
        "4) 提交计划倒排到发运日；缓冲不足标红。" + _COMMON_RED.format(审核角色="后期经理"),
    ),

    # ================= 屏蔽泵事业部 =================
    _rule(
        "SC-PMP-201", "屏蔽泵选型与数据表（屏蔽泵事业部成熟规则初稿）",
        "屏蔽泵事业部", "dev",
        "机械工程师（屏蔽泵）/ 主管 / 技术副总（审核放行）",
        "客户询价、技术澄清、方案比选时",
        "选型逻辑 + 数据表骨架 + 待确认项，技术审核后放行",
        "deepseek", "kimi",
        "性能不编造；结构特征与选型一致；待计算项显式列出",
        [
            {"code": "KPI-PMP-FILE", "name": "技术文件编制数", "weight": "20%", "dimension": "V-价值创造", "source": "简道云[任务管理]"},
            {"code": "KPI-PMP-REVIEW", "name": "设计评审通过率", "weight": "15%", "dimension": "V-价值创造", "source": "简道云[任务/评审]"},
        ],
        [
            {"key": "duty", "label": "工况", "required": True,
             "placeholder": "介质/流量/扬程/温度/压力/NPSH/密度粘度"},
            {"key": "std", "label": "执行标准", "required": False, "placeholder": "API685 / ISO / GB"},
            {"key": "material", "label": "材质要求", "required": False, "placeholder": ""},
            {"key": "option", "label": "候选型号或配置", "required": False, "placeholder": ""},
        ],
        "你是 V-FLO 屏蔽泵事业部设计工程师。\n工况：{{duty}}\n标准：{{std}}\n"
        "材质：{{material}}\n候选：{{option}}\n\n"
        "【执行规则】\n"
        "1) 输出：工况理解表、选型逻辑（必需汽蚀余量/效率/功率估算口径）、推荐型号特征、"
        "数据表字段骨架、必须计算与确认清单（水力/热力/转子动力/电磁/强度）。\n"
        "2) 不得编造性能曲线精确值；缺参数标「待计算/待客户提供」。\n"
        "3) 标准要求给出 GB 等同映射提示（若适用）。" + _COMMON_RED.format(审核角色="技术副总"),
    ),

    # ================= 研发设计部 =================
    _rule(
        "SC-RND-201", "NCR处置建议书（研发设计部成熟规则初稿）",
        "研发设计部", "dev",
        "产品研发工程师 / 部门主管 / 研发设计经理（审核放行）",
        "不合格品/NCR 产生后",
        "问题定义—原因假设—处置方案—纠正预防，质量/研发会签后执行",
        "deepseek", "mimo",
        "处置三选一明确（返工/让步/报废）；验证闭环；可进简道云任务",
        [
            {"code": "KPI-RND-03", "name": "NCR处置参与及时率", "weight": "10%", "dimension": "V-价值创造", "source": "简道云[任务管理]"},
            {"code": "KPI-RND-IMP", "name": "流程改进项目数", "weight": "10%", "dimension": "O-优化创新", "source": "简道云[项目结项/意见箱]"},
        ],
        [
            {"key": "ncr", "label": "NCR事实", "required": True, "placeholder": "产品/工序/缺陷/数量/标准要求"},
            {"key": "cause", "label": "原因线索", "required": False, "placeholder": ""},
            {"key": "constraint", "label": "约束", "required": False, "placeholder": "交期/成本/客户要求"},
        ],
        "你是 V-FLO 研发设计部工程师，编写 NCR 处置建议。\n"
        "事实：{{ncr}}\n线索：{{cause}}\n约束：{{constraint}}\n\n"
        "【执行规则】\n"
        "1) 输出：问题定义（5W2H）、原因假设（已证实/待证实）、处置方案比较"
        "（返工/让步接收/报废三选一及理由）、纠正与预防措施、验证方式、遗留风险。\n"
        "2) 禁止编造检测数据；影响性能/安全时强制「升级评审」。\n"
        "3) 建议可录入简道云的 2 条任务（五要素）。" + _COMMON_RED.format(审核角色="研发设计经理"),
    ),

    # ================= 生产部 =================
    _rule(
        "SC-PRD-201", "生产日报与异常升级（生产部成熟规则初稿）",
        "生产部", "general",
        "班组长 / 生产文员 / 生产部长（审核放行）",
        "每日下班前",
        "产量/进度/异常/明日计划四段日报，可直接传简道云",
        "mimo", "deepseek",
        "产量有数；异常有升级；对接计划员与质量",
        [
            {"code": "KPI-PRD-01", "name": "任务完成数", "weight": "8-15%", "dimension": "V-价值创造", "source": "简道云[任务管理]"},
            {"code": "KPI-PRD-DOC", "name": "文档记录完整度", "weight": "15%", "dimension": "O-优化创新", "source": "简道云[内部资料/任务附件]"},
        ],
        [
            {"key": "team", "label": "班组/产线", "required": True, "placeholder": ""},
            {"key": "output", "label": "完成情况", "required": True, "placeholder": "工单/件数/工时"},
            {"key": "issues", "label": "异常", "required": True, "placeholder": "设备/质量/物料/人员，无则写无"},
            {"key": "tomorrow", "label": "明日安排", "required": False, "placeholder": ""},
        ],
        "你是 V-FLO 生产部文员助理。\n班组：{{team}}\n完成：{{output}}\n"
        "异常：{{issues}}\n明日：{{tomorrow}}\n\n"
        "【执行规则】\n"
        "1) 输出四段：①今日完成（对照计划）②异常与处理（现象|影响|已做|待协调|升级对象）"
        "③质量/安全提示 ④明日计划。\n"
        "2) 异常必须可升级：写清需要谁在何时做什么。\n"
        "3) 语言简洁，班组可读；可直接作简道云任务附件。" + _COMMON_RED.format(审核角色="生产部长"),
    ),

    # ================= 财务部 =================
    _rule(
        "SC-FIN-201", "结账与报表编制检查单（财务部成熟规则初稿）",
        "财务部", "general",
        "财务经理 / 会计 / 主管会计（审核放行）",
        "月/季结账前",
        "检查单+未完成项责任倒排，保证报表及时准确",
        "deepseek", "mimo",
        "不涉及编造金额；检查项可勾选；与税期联动",
        [
            {"code": "KPI-FIN-01", "name": "财务报表出具及时率", "weight": "15-18%", "dimension": "V-价值创造", "source": "简道云[开票/回款]"},
            {"code": "KPI-FIN-03", "name": "凭证差错次数", "weight": "15-20%", "dimension": "V-价值创造", "source": "简道云[付款/回款单]"},
        ],
        [
            {"key": "period", "label": "期间", "required": True, "placeholder": "2026-09"},
            {"key": "status", "label": "结账进度", "required": True, "placeholder": "已完/未完事项"},
            {"key": "entities", "label": "涉及公司/主体", "required": False, "placeholder": "13家公司等"},
        ],
        "你是 V-FLO 财务部结账助理。\n期间：{{period}}\n进度：{{status}}\n主体：{{entities}}\n\n"
        "【执行规则】\n"
        "1) 输出结账检查单：序号|检查项|责任人|完成时限|状态；覆盖往来核对、折旧摊销、"
        "成本结转、税金计提、凭证复核、关账清单。\n"
        "2) 常见差错点清单（对应凭证差错 KPI）。\n"
        "3) 报表出具与报税征期倒排。禁止编造金额。" + _COMMON_RED.format(审核角色="财务经理"),
    ),

    # ================= 人事行政部 =================
    _rule(
        "SC-HR-201", "岗位说明书与结构化面试包（人事行政部成熟规则初稿）",
        "人事行政部", "general",
        "人事主管 / 人事行政专员 / 经理（审核放行）",
        "启动招聘或岗位调整时",
        "JD + 任职资格 + 结构化面试题与评分表，经理审定后发布",
        "kimi", "mimo",
        "职责可考核；面试题可评分；对齐四维绩效",
        [
            {"code": "KPI-HR-01", "name": "招聘完成数", "weight": "15-20%", "dimension": "V-价值创造", "source": "简道云[任务-招聘类]"},
            {"code": "KPI-HR-03", "name": "人才储备完成度", "weight": "10%", "dimension": "O-优化创新", "source": "简道云[任务-人才储备]"},
        ],
        [
            {"key": "position", "label": "岗位名称", "required": True, "placeholder": ""},
            {"key": "dept", "label": "所属部门", "required": True, "placeholder": ""},
            {"key": "must", "label": "硬性要求", "required": True, "placeholder": "学历/经验/技能/证书"},
            {"key": "kpi_hint", "label": "关键考核点", "required": False, "placeholder": ""},
        ],
        "你是 V-FLO 人事行政部 HR 专家。\n岗位：{{position}}\n部门：{{dept}}\n"
        "硬性要求：{{must}}\n考核点：{{kpi_hint}}\n\n"
        "【执行规则】\n"
        "1) 输出：岗位目的、职责 3–5 条（可考核）、任职资格、"
        "结构化面试题 5 道及评分要点、面试评价表（含四维绩效对齐项）、薪酬区间建议占位「待人资总监定」。\n"
        "2) 禁止编造薪资数字与职级。" + _COMMON_RED.format(审核角色="人事行政经理"),
    ),

    # ================= 总经办 =================
    _rule(
        "SC-GM-201", "月度经营分析一页纸（总经办成熟规则初稿）",
        "总经办", "general",
        "总经理 / 常务副总 / 营销副总 / 技术副总（审核放行）",
        "月度经营会前",
        "结论先行的经营分析 + 决策选项，供经营会决策",
        "deepseek", "kimi",
        "数据不编造；决策选项含利弊与回滚；支撑决策质量评分",
        [
            {"code": "KPI-GM-01", "name": "销售额/回款额", "weight": "15-20%", "dimension": "V-价值创造", "source": "简道云[CRM-订单/回款]"},
            {"code": "KPI-GM-DECIDE", "name": "决策质量", "weight": "15%", "dimension": "L-连接协同", "source": "简道云[任务-决策评审/AI评分]"},
            {"code": "KPI-GM-INSIGHT", "name": "业务洞察", "weight": "10-12%", "dimension": "L-连接协同", "source": "简道云[市场活动/线索]"},
        ],
        [
            {"key": "period", "label": "期间", "required": True, "placeholder": ""},
            {"key": "data", "label": "经营数据要点", "required": True,
             "placeholder": "销售/回款/交付/质量/人效/重点单"},
            {"key": "issues", "label": "重大议题", "required": True, "placeholder": "待决策事项"},
        ],
        "你是 V-FLO 总经办经营分析助理。\n期间：{{period}}\n数据：{{data}}\n议题：{{issues}}\n\n"
        "【执行规则】\n"
        "1) 输出一页纸：总体结论（红黄绿）、关键指标表、问题根因（已证实/待证实）、"
        "决策选项（各方案收益/风险/资源/周期）、建议与触发回滚条件、下周动作到人。\n"
        "2) 数据缺失写「未提供」，不得臆造经营数字。\n"
        "3) 语言供决策会直接使用，结论先行。" + _COMMON_RED.format(审核角色="总经理"),
    ),

    # ================= 威标部 =================
    _rule(
        "SC-AI-201", "智能体需求任务书（威标部成熟规则初稿）",
        "威标部", "dev",
        "AI开发工程师 / 威标部负责人（审核放行）",
        "各部门提出智能体/数字化需求后",
        "生成简道云五要素齐全、可开发验收的任务书",
        "deepseek", "kimi",
        "五要素完整；验收可测；不空泛",
        [
            {"code": "KPI-AI-PLAN", "name": "任务规划完整度", "weight": "8%", "dimension": "O-优化创新", "source": "简道云[任务-五要素完整]"},
            {"code": "KPI-AI-01", "name": "任务完成率", "weight": "12%", "dimension": "V-价值创造", "source": "简道云[任务管理]"},
            {"code": "KPI-AI-04", "name": "智能体开发项目参与数", "weight": "8%", "dimension": "V-价值创造", "source": "简道云[关联项目]"},
        ],
        [
            {"key": "request", "label": "业务需求描述", "required": True, "placeholder": "口语描述即可"},
            {"key": "dept", "label": "需求部门/岗位", "required": True, "placeholder": ""},
            {"key": "deadline", "label": "期望完成时间", "required": True, "placeholder": ""},
            {"key": "users", "label": "目标用户/规模", "required": False, "placeholder": ""},
        ],
        "你是 V-FLO 威标部 AI 产品经理。\n需求：{{request}}\n部门岗位：{{dept}}\n"
        "期望：{{deadline}}\n用户：{{users}}\n\n"
        "【执行规则】\n"
        "1) 输出任务书：背景、目标、用户故事、简道云任务五要素"
        "（任务标题、开始时间、截止时间、负责人、优先级、所属项目）、"
        "功能清单、输入输出、验收标准（可测）、依赖与风险、预计工作量。\n"
        "2) 验收标准禁止「体验良好」类空话，必须可勾选。\n"
        "3) 标注是否涉及出口管制/敏感数据。" + _COMMON_RED.format(审核角色="威标部负责人"),
    ),

    # ================= 通用（部门领导可认领） =================
    _rule(
        "SC-GEN-201", "跨部门会议纪要与行动项（通用成熟规则初稿）",
        "通用", "general",
        "全体参会人 / 会议召集人（审核放行）",
        "跨部门会议结束后 30 分钟内",
        "结论+分歧+行动项表，可一键进简道云",
        "mimo", "kimi",
        "行动项到人到日；分歧显式；与会各方口径一致",
        [
            {"code": "KPI-GEN-AI", "name": "工作完成质量(AI)", "weight": "5-16%", "dimension": "L-连接协同", "source": "简道云[任务-AI评分]"},
            {"code": "KPI-GEN-DOC", "name": "文档记录完整度", "weight": "5-16%", "dimension": "O-优化创新", "source": "简道云[内部资料]"},
        ],
        [
            {"key": "meeting", "label": "会议名称/主题", "required": True, "placeholder": ""},
            {"key": "attendees", "label": "参会人", "required": True, "placeholder": ""},
            {"key": "notes", "label": "会议要点（口语）", "required": True, "placeholder": ""},
            {"key": "decisions", "label": "已决/未决", "required": False, "placeholder": ""},
        ],
        "你是 V-FLO 会议纪要助理。\n会议：{{meeting}}\n参会：{{attendees}}\n"
        "要点：{{notes}}\n决策情况：{{decisions}}\n\n"
        "【执行规则】\n"
        "1) 输出：会议结论、分歧点、行动项表（事项|责任人|截止日|关联简道云任务）、下次会议安排。\n"
        "2) 行动项必须到人到日；未决事项单独列表。\n"
        "3) 不写空话评价，只写事实与决定。" + _COMMON_RED.format(审核角色="会议召集人"),
    ),
]
