# -*- coding: utf-8 -*-
"""T13 场景卡种子库 v2 —— 按《20260916 各部门岗位职责和KPI指标》对齐。
每张卡 = 提示词资产 + 简道云KPI关联 + 推荐模型 + 出口管制标记。
部门以集团真实设置为准：总经办/商务部/项目部/工程技术部(前期|后期)/屏蔽泵事业部/
研发设计部/生产部/质检部/财务部/人事行政部/威标部/通用。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import Scenario

# 标准开工：①建任务资料文件夹 ②Mimo V2.6 新建项目并绑定 ③按 usage_steps 推进工作流
# code -> (workflow_stage, usage_steps)
WORKFLOW_MAP = {'SC-PRJ-001': ('项目执行-周报', '①收集本周事实 ②填空 ③生成 ④改稿 ⑤发客户/上级并归档'), 'SC-PRJ-002': ('售前-询价投标', '①读标书 ②填范围与国别 ③生成方案骨架 ④补澄清问题 ⑤交经理审核'), 'SC-PRJ-003': ('售前-澄清闭环', '①粘贴客户问题 ②写我方要点 ③生成回复 ④经理确认 ⑤发出并归档'), 'SC-PRJ-004': ('执行-合同交接', '①摘关键条款 ②生成交接包 ③发各接口部门 ④建简道云项目任务'), 'SC-PRJ-005': ('执行-风险管控', '①填进度事实 ②生成风险表 ③会前发经理'), 'SC-PRJ-006': ('执行-俄文文件', '①粘贴俄文 ②生成摘要与冲突点 ③内部交底'), 'SC-PRJ-007': ('收尾-知识沉淀', '①写经过与经验 ②生成条目 ③上传简道云知识库'), 'SC-SAL-001': ('销售-周经营', '①填数据要点 ②生成周报 ③发经理会'), 'SC-SAL-002': ('销售-客户沟通', '①选语言 ②写目的要点 ③生成邮件 ④发出'), 'SC-SAL-003': ('销售-合同审核', '①粘贴条款 ②生成风险表 ③经理/法务复核'), 'SC-SAL-004': ('跟单-六块管控', '①填六块现状 ②生成看板摘要 ③项目会使用'), 'SC-SAL-005': ('采购-比价催交', '①选用途 ②填信息 ③生成比价/催交函'), 'SC-SAL-006': ('市场-洞察沉淀', '①填活动信息 ②生成洞察 ③录简道云市场活动'), 'SC-ENG-001': ('售前-选型', '①填工况 ②填候选 ③生成对比 ④交报价'), 'SC-ENG-002': ('售前-成本', '①填BOM要点 ②生成成本骨架 ③定价评审'), 'SC-ENG-003': ('售前-需求解析', '①粘贴规格书 ②生成澄清清单 ③发客户'), 'SC-ENG-011': ('交付-文件计划', '①填订单与文件要求 ②生成清单 ③建任务跟踪'), 'SC-ENG-012': ('交付-批复处理', '①粘贴批复 ②生成处理单 ③3日内回复'), 'SC-ENG-013': ('交付-三维修改', '①填修改与零件 ②生成核对清单 ③改模'), 'SC-PMP-001': ('研发-选型设计', '①填工况 ②生成选型与数据表 ③评审'), 'SC-PMP-002': ('研发-计算校核', '①填设计对象 ②生成计算书结构 ③评审'), 'SC-RND-001': ('研发-立项计划', '①填项目目标 ②生成计划 ③录入简道云五要素'), 'SC-RND-002': ('质量-NCR处置', '①填NCR事实 ②生成处置建议 ③验证关闭'), 'SC-RND-003': ('研发-BOM变更', '①填变更明细 ②生成变更单 ③通知采购/生产'), 'SC-PRD-001': ('生产-日报交接', '①填完成与异常 ②生成日报 ③传简道云'), 'SC-PRD-002': ('生产-设备保障', '①填设备现象 ②生成报修单 ③报修'), 'SC-PRD-003': ('生产-工艺培训', '①填工序 ②生成要点卡 ③班组学习'), 'SC-QA-001': ('质量-问题闭环', '①填问题 ②生成8D ③内部评审后回复客户'), 'SC-QA-002': ('质量-月度改进', '①填质量数据 ②生成月报 ③质量会'), 'SC-QA-003': ('质量-检验记录', '①填检验结果 ②生成规范记录 ③归档'), 'SC-FIN-001': ('财务-结账', '①填进度 ②生成检查单 ③按单结账'), 'SC-FIN-002': ('财务-税务', '①填税种公司 ②生成提醒清单 ③申报'), 'SC-FIN-003': ('财务-报销', '①填单据 ②生成初审要点 ③入账'), 'SC-HR-001': ('人力-招聘', '①填岗位要求 ②生成JD面试题 ③发布'), 'SC-HR-002': ('人力-培训', '①填培训信息 ②生成纪要学时 ③录简道云'), 'SC-HR-003': ('人力-绩效', '①填事实 ②生成面谈提纲 ③面谈'), 'SC-HR-004': ('人力-行政', '①填要点 ②生成通知 ③发布'), 'SC-GM-001': ('经营-月度分析', '①填数据议题 ②生成一页纸 ③经营会'), 'SC-GM-002': ('经营-战略执行', '①填战略要点 ②生成任务分解 ③录简道云'), 'SC-GM-003': ('经营-决策评审', '①填事项方案 ②生成评审材料 ③决策会'), 'SC-AI-001': ('AI-需求立项', '①填需求 ②生成任务书 ③录简道云'), 'SC-AI-002': ('AI-质量评审', '①填变更摘要 ②生成审查意见 ③合并'), 'SC-AI-003': ('日常-任务管理', '①粘贴口语任务 ②润色 ③粘贴进简道云'), 'SC-EXP-001': ('合规-出口初筛', '①填客户国别用途产品 ②生成审查单 ③合规官审核'), 'SC-EXP-002': ('合规-EUC', '①填主体物项用途 ②生成EUC ③合规官审定签署'), 'SC-EXP-003': ('合规-条款审查', '①粘贴条款 ②生成覆盖检查 ③补条款'), 'SC-EXP-004': ('合规-技术外发', '①填资料接收方 ②生成边界确认 ③获批后再发'), 'SC-EXP-005': ('合规-红旗升级', '①填异常事实 ②生成报告 ③立即升级'), 'SC-EXP-006': ('合规-培训', '①填对象 ②生成培训测验 ③组织培训'), 'SC-GEN-001': ('日常-邮件', '①填目的草稿 ②润色 ③发送'), 'SC-GEN-002': ('日常-学习沉淀', '①粘贴文档 ②生成摘要条目 ③入知识库'), 'SC-GEN-003': ('日常-汇报', '①填主题要点 ②生成大纲讲稿 ③汇报'), 'SC-GEN-004': ('日常-数据分析', '①填数据问题 ②生成结论 ③展示')}

# KPI 维度缩写：V=价值创造 F=流程效率 L=连接协同 O=优化创新
# source 对应简道云模块（便于后续对接取数）
# example_input/example_output 由 AI 起草（v2.1），待各部门业务 Owner 审改签字


def K(code, name, weight, dim, source):
    return {"code": code, "name": name, "weight": weight, "dimension": dim, "source": source}


SCENARIOS: list[dict] = [
    # ================= 项目部（70%时间做项目执行） =================
    {
        "code": "SC-PRJ-001", "title": "项目周报生成", "department": "项目部", "category": "project",
        "roles": "项目部经理 / 主管 / 项目工程师",
        "timing": "每周五或客户索要周报时",
        "goal": "输出可对外发送的项目周报，支撑「项目按时完成率」与「工作完成质量(AI)」",
        "default_model": "kimi", "fallback_model": "mimo",
        "kpi_links": [
            K("KPI-PRJ-01", "项目按时完成率", "27%", "V-价值创造", "简道云[项目管理→项目计划/结项]"),
            K("KPI-PRJ-03", "工作完成质量(AI)", "16%", "L-连接协同", "简道云[任务管理-AI评分]"),
            K("KPI-PRJ-02", "文档记录完整度", "16%", "O-优化创新", "简道云[内部资料/任务附件]"),
        ],
        "variables": [
            {"key": "project_name", "label": "项目名称", "required": True, "placeholder": "如：俄罗斯XX泵站"},
            {"key": "week_progress", "label": "本周进展要点", "required": True, "placeholder": "每行一条，带日期与完成度"},
            {"key": "risks", "label": "风险与问题", "required": True, "placeholder": "无则写“本周无重大风险”"},
            {"key": "next_plan", "label": "下周计划", "required": True, "placeholder": "带责任人与时间"},
            {"key": "customer", "label": "客户/最终用户", "required": False, "placeholder": "选填"},
        ],
        "prompt_template": (
            "你是 V-FLO 项目部资深项目助理，熟悉国际泵阀/屏蔽泵成套项目执行。\n"
            "请生成《项目周报》，要求正式、可对外发送，同时便于上传简道云任务附件（利于文档完整度）。\n\n"
            "项目名称：{{project_name}}\n客户/最终用户：{{customer}}\n\n"
            "## 本周进展\n{{week_progress}}\n\n## 风险与问题\n{{risks}}\n\n## 下周计划\n{{next_plan}}\n\n"
            "输出格式：\n1. 标题（项目+周报+日期）\n2. 一句话本周结论\n3. 本周进展（分条+完成度）\n"
            "4. 风险表（风险/影响/责任人/建议措施/截止日）\n5. 下周计划表（事项/责任人/完成时间）\n"
            "6. 需协调事项\n约束：不编造数据；语言书面简洁；结论体现「是否按期」以支撑按时完成率考核。"
        ),
        "quality_notes": "风险必须有应对与日期；下周计划到人到日；结论明确是否影响节点。",
        "example_input": "俄罗斯XX泵站；进展：GA图提交9/25；风险：客户延迟确认材质；下周：跟进确认，李腾龙，10/2前",
        "example_output": "（结构完整周报，风险表含责任人与建议）",
        "output_format": "markdown",
    },
    {
        "code": "SC-PRJ-002", "title": "投标技术方案初稿（前期询价）", "department": "项目部", "category": "project",
        "roles": "项目工程师 / 项目部经理（审核）",
        "timing": "收到询价/标书后 24–48 小时内",
        "goal": "技术方案+商务要点骨架，提高中标率与报价及时率",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-PRJ-04", "中标率", "5%", "V-价值创造", "简道云[CRM-商机管理]"),
            K("KPI-PRJ-01", "项目按时完成率", "27%", "V-价值创造", "简道云[项目管理]"),
            K("KPI-PRJ-05", "任务完成数", "21%", "V-价值创造", "简道云[任务管理]"),
        ],
        "variables": [
            {"key": "inquiry_no", "label": "询价/标书编号", "required": True, "placeholder": ""},
            {"key": "scope", "label": "供货范围与技术要点", "required": True, "placeholder": "介质/流量扬程/材质/标准/交期"},
            {"key": "customer", "label": "客户与国别", "required": True, "placeholder": "用于合规提示"},
            {"key": "strategy", "label": "报价策略提示", "required": False, "placeholder": "低价抢点/技术差异化等"},
        ],
        "prompt_template": (
            "你是 V-FLO 项目部投标工程师，擅长石化流程泵/屏蔽泵国际项目。\n"
            "询价：{{inquiry_no}}\n客户与国别：{{customer}}\n范围：{{scope}}\n策略：{{strategy}}\n\n"
            "输出：\n1. 需求理解摘要\n2. 技术方案章节骨架（配置建议/执行标准/供货边界/文件清单）\n"
            "3. 澄清问题清单（问客户）\n4. 商务要点（交期/付款/质保/验收）\n5. 风险提示（含出口管制需确认项）\n"
            "约束：不编造参数；缺失参数列入澄清；涉及出口目的地时提示先做合规初筛。"
        ),
        "quality_notes": "参数不得编造，缺失参数必须列入澄清清单；涉出口目的地时提示合规初筛。",
        "example_input": "RFQ-2026-018；范围：屏蔽泵2台，介质液氨，Q=25m³/h，H=80m，API685，交期20周；客户：俄罗斯某石化公司；策略：技术差异化",
        "example_output": "（需求摘要+方案章节骨架+澄清问题清单+商务要点+风险提示的投标方案初稿）",
        "output_format": "markdown",
    },
    {
        "code": "SC-PRJ-003", "title": "技术澄清回复函（中俄/中英）", "department": "项目部", "category": "project",
        "roles": "项目工程师",
        "timing": "客户澄清函到达后（目标3个工作日内回复）",
        "goal": "闭环澄清，提升成单率与文档完整度",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-PRJ-03", "工作完成质量(AI)", "16%", "L-连接协同", "简道云[任务管理-AI评分]"),
            K("KPI-PRJ-02", "文档记录完整度", "16%", "O-优化创新", "简道云[内部资料]"),
        ],
        "variables": [
            {"key": "lang", "label": "回复语言", "required": True, "placeholder": "中文 / English / Русский"},
            {"key": "questions", "label": "客户问题原文", "required": True, "placeholder": ""},
            {"key": "our_stand", "label": "我方立场/技术答复要点", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是 V-FLO 项目技术澄清专家，精通中英俄商务技术函电。\n"
            "语言：{{lang}}\n客户问题：\n{{questions}}\n\n我方答复要点：{{our_stand}}\n\n"
            "输出正式澄清回复：逐条编号对应；结论明确（可满足/有条件满足/需澄清）；"
            "有不确定处写[待确认]；文末附「需客户确认事项」。禁止编造标准号与参数。"
        ),
        "quality_notes": "逐条编号对应客户问题；结论明确（可满足/有条件满足/需澄清）；不确定处标[待确认]，禁止编造标准号。",
        "example_input": "语言：中文；客户问题：1.泵是否满足API685？2.能否12周交货？；我方要点：1.满足并可附业绩表 2.常规16周，可评估加急",
        "example_output": "（逐条编号对应的正式澄清回复函，文末附需客户确认事项）",
        "output_format": "email",
    },
    {
        "code": "SC-PRJ-004", "title": "合同执行通知/交接包", "department": "项目部", "category": "project",
        "roles": "项目工程师 / 项目部主管",
        "timing": "收到外贸订单/合同后",
        "goal": "合同评审交接包，文件计划骨架",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-PRJ-01", "项目按时完成率", "27%", "V-价值创造", "简道云[项目管理]"),
            K("KPI-PRJ-02", "文档记录完整度", "16%", "O-优化创新", "简道云[内部资料]"),
        ],
        "variables": [
            {"key": "contract_no", "label": "合同/订单号", "required": True, "placeholder": ""},
            {"key": "key_terms", "label": "关键条款", "required": True, "placeholder": "范围/交期/价格/验收/罚则/目的地"},
            {"key": "tech_points", "label": "技术要点", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是 V-FLO 合同执行工程师。生成《合同执行通知》与文件计划骨架。\n"
            "合同：{{contract_no}}\n关键条款：{{key_terms}}\n技术要点：{{tech_points}}\n\n"
            "输出：1) 合同要点摘录 2) 交底各部门事项表 3) 文件交付清单骨架 4) 风险与出口合规提示 5) 里程碑建议。"
        ),
        "quality_notes": "条款摘录忠于合同原文；交底事项到部门到事；含风险与出口合规提示。",
        "example_input": "合同号：VF-2026-088；关键条款：交期20周/预付30%/目的地哈萨克斯坦/逾期罚0.5%每周；技术要点：屏蔽泵+变频控制成套供货",
        "example_output": "（合同要点摘录+部门交底事项表+文件交付清单骨架+合规提示+里程碑建议的交接包）",
        "output_format": "document",
    },
    {
        "code": "SC-PRJ-005", "title": "项目进度风险摘要", "department": "项目部", "category": "project",
        "roles": "项目部经理 / 主管",
        "timing": "例会前、里程碑前、客户升级前",
        "goal": "一页风险矩阵，支撑管理决策与按时完成率",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-PRJ-01", "项目按时完成率", "27%", "V-价值创造", "简道云[项目管理]"),
            K("KPI-PRJ-06", "三化推进完成度", "16%", "O-优化创新", "简道云[任务-三化建设]"),
        ],
        "variables": [
            {"key": "facts", "label": "事实与数据", "required": True, "placeholder": "进度%、延期天数、缺项、客户批复"},
            {"key": "milestone", "label": "当前节点", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是 V-FLO 项目风险分析师。只基于事实输出风险摘要。\n"
            "节点：{{milestone}}\n事实：{{facts}}\n\n"
            "输出：总体红黄绿判断；风险矩阵表；需管理层拍板事项；7天行动清单。"
        ),
        "quality_notes": "只基于输入事实判断，不推测编造；红黄绿结论明确；行动清单到人到日、7天内可执行。",
        "example_input": "节点：GA图批复；事实：提交已10天未批复，进度65%落后计划5天，材质确认缺项",
        "example_output": "（红黄绿结论+风险矩阵表+待拍板事项+7天行动清单的一页风险摘要）",
        "output_format": "markdown",
    },
    {
        "code": "SC-PRJ-006", "title": "俄罗斯项目文件解读", "department": "项目部", "category": "project",
        "roles": "项目工程师 / 商务跟单",
        "timing": "收到俄语技术文件/澄清/标准",
        "goal": "中文摘要+参数表+冲突点",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [K("KPI-PRJ-03", "工作完成质量(AI)", "16%", "L-连接协同", "简道云[任务管理-AI评分]")],
        "variables": [
            {"key": "source_text", "label": "俄文原文", "required": True, "placeholder": "粘贴俄文"},
            {"key": "focus", "label": "关注点", "required": False, "placeholder": "交期/材质/验收/标准"},
        ],
        "prompt_template": (
            "你是熟悉俄罗斯项目的资深技术翻译。\n关注点：{{focus}}\n\n原文：\n{{source_text}}\n\n"
            "输出：中文摘要；关键条款表(原文|中文|备注)；与我方冲突点；建议回复要点。不确定译文标[待确认]。"
        ),
        "quality_notes": "译文忠于原文，不确定处标[待确认]；冲突点须引用原文条款对照说明。",
        "example_input": "俄文：Срок поставки — не более 20 недель с даты вступления контракта в силу...；关注点：交期与验收",
        "example_output": "（中文摘要+关键条款中俄对照表+冲突点+建议回复要点）",
        "output_format": "markdown",
    },
    {
        "code": "SC-PRJ-007", "title": "知识库沉淀与经验归档（支撑AI评分）", "department": "项目部", "category": "project",
        "roles": "全体项目成员",
        "timing": "项目节点完成/问题解决后",
        "goal": "产出可上传简道云知识库的高质量文档，直接拉高知识沉淀分",
        "default_model": "mimo", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-PRJ-02", "文档记录完整度", "16%", "O-优化创新", "简道云[知识库/内部资料]"),
            K("KPI-PRJ-03", "工作完成质量(AI)", "16%", "L-连接协同", "简道云[任务管理-AI评分]"),
            K("KPI-AI-DOC", "知识沉淀与主动性(AI)", "10%", "L-连接协同", "简道云[知识库]"),
        ],
        "variables": [
            {"key": "topic", "label": "主题", "required": True, "placeholder": "问题/经验/模板使用心得"},
            {"key": "facts", "label": "经过与关键事实", "required": True, "placeholder": ""},
            {"key": "lessons", "label": "可复用经验", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是知识管理助理。把经验整理成可入库的规范条目。\n"
            "主题：{{topic}}\n经过：{{facts}}\n经验：{{lessons}}\n\n"
            "输出结构：背景—问题—解决过程—可复用规则—适用范围—关联模板/智能体场景。\n"
            "文风要体现技术深度与可维护性（AI评分维度），避免流水账。"
        ),
        "quality_notes": "必须有可复用规则；写清适用范围；避免只写“顺利完成”。",
        "example_input": "主题：俄项目GA图批复周期长的应对；经过：客户批复平均21天，经预审会议+双语摘要缩短至10天；经验：提交前约批复会议、随附双语摘要",
        "example_output": "（背景—问题—解决过程—可复用规则—适用范围—关联场景的入库条目）",
        "output_format": "markdown",
    },

    # ================= 商务部 =================
    {
        "code": "SC-SAL-001", "title": "销售周报/回款跟进", "department": "商务部", "category": "sales",
        "roles": "国际销售主管 / 国际销售 / 商务部经理",
        "timing": "每周五",
        "goal": "业绩与漏斗结构化周报",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-SAL-01", "销售额/回款额", "25%", "V-价值创造", "简道云[CRM-订单/回款单]"),
            K("KPI-SAL-02", "订单数", "10%", "V-价值创造", "简道云[CRM-销售订单]"),
            K("KPI-SAL-03", "新增客户数", "10%", "V-价值创造", "简道云[CRM-客户]"),
            K("KPI-SAL-08", "业务洞察", "8-10%", "L-连接协同", "简道云[市场活动/线索]"),
        ],
        "variables": [
            {"key": "period", "label": "周期", "required": True, "placeholder": "2026-W39"},
            {"key": "numbers", "label": "数据要点", "required": True, "placeholder": "签约/回款/新增客户/重点单"},
            {"key": "highlights", "label": "亮点与困难", "required": False, "placeholder": ""},
        ],
        "prompt_template": (
            "你是 V-FLO 商务部销售运营助理。生成销售周报。\n周期：{{period}}\n数据：{{numbers}}\n亮点困难：{{highlights}}\n\n"
            "输出：核心指标表（对照回款/订单/新客）；漏斗分析；Top机会；风险单；下周打法。数据缺失写“未提供”。"
        ),
        "quality_notes": "数据缺失写“未提供”，不得估算编造；核心指标与回款/订单/新客目标对照。",
        "example_input": "周期：2026-W39；数据：签约2单180万/回款95万/新增客户3家；亮点困难：俄客户付款延迟",
        "example_output": "（核心指标表+漏斗分析+Top机会+风险单+下周打法的结构化周报）",
        "output_format": "markdown",
    },
    {
        "code": "SC-SAL-002", "title": "客户邮件（中/英/俄/波斯语等）", "department": "商务部", "category": "sales",
        "roles": "国际销售 / 项目跟单 / 商务专员",
        "timing": "日常对外沟通",
        "goal": "专业多语种邮件定稿",
        "default_model": "kimi", "fallback_model": "mimo",
        "kpi_links": [
            K("KPI-SAL-MAIL", "邮件响应及时率和有效性", "12%", "F-流程效率", "简道云/邮件系统"),
            K("KPI-SAL-05", "客户投诉次数", "7-10%", "F-流程效率", "简道云[跟进记录]"),
        ],
        "variables": [
            {"key": "language", "label": "语言", "required": True, "placeholder": "中文/English/Русский/فارسی"},
            {"key": "purpose", "label": "目的", "required": True, "placeholder": ""},
            {"key": "key_points", "label": "要点", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是 V-FLO 国际商务写作专家。\n语言：{{language}}\n目的：{{purpose}}\n要点：{{key_points}}\n\n"
            "输出完整邮件（主题+正文+落款）。语气专业克制；含行动号召；不承诺未授权事项。"
        ),
        "quality_notes": "语气专业克制；含明确行动号召；不承诺未授权事项。",
        "example_input": "语言：English；目的：催客户批复数据表；要点：已提交10天/影响排产/请本周五前回复",
        "example_output": "（主题+正文+落款的完整邮件，含明确行动号召）",
        "output_format": "email",
    },
    {
        "code": "SC-SAL-003", "title": "合同/协议条款初审清单", "department": "商务部", "category": "sales",
        "roles": "商务部经理 / 副经理 / 国际销售主管",
        "timing": "合同/合作协议定稿前",
        "goal": "风险清单+修改建议（非法务意见）",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-SAL-REVIEW", "报价、技术方案、商务条款审核质量", "15%", "O-优化创新", "简道云/评审记录"),
            K("KPI-SAL-05", "客户投诉次数", "7%", "F-流程效率", "简道云[跟进记录]"),
        ],
        "variables": [
            {"key": "clauses", "label": "条款文本", "required": True, "placeholder": "粘贴付款/验收/违约/质保/争议等"},
        ],
        "prompt_template": (
            "你是 V-FLO 商务合同风险初筛助理（不提供法律意见）。\n条款：\n{{clauses}}\n\n"
            "输出：高中低风险表（条款/风险/影响/建议表述）；出口管制与制裁条款是否覆盖；"
            "结尾注明需法务/合规官复核。"
        ),
        "quality_notes": "按高/中/低风险分级并给出建议表述；出口管制与制裁条款覆盖性必查；结尾注明需法务复核。",
        "example_input": "条款：付款30%预付70%发货前；验收：到港后30天；违约：逾期0.3%/周；争议：新加坡仲裁",
        "example_output": "（高/中/低风险表+出口管制覆盖检查+法务复核提示的初审清单）",
        "output_format": "table",
    },
    {
        "code": "SC-SAL-004", "title": "项目跟单六块看板摘要", "department": "商务部", "category": "sales",
        "roles": "项目跟单主管 / 项目跟单",
        "timing": "每周项目会前",
        "goal": "文件/生产/检验/收款/澄清/发货六块状态",
        "default_model": "deepseek", "fallback_model": "mimo",
        "kpi_links": [
            K("KPI-SAL-04", "订单交付准时率", "7-18%", "V-价值创造", "简道云[销售订单/出库]"),
            K("KPI-SAL-CLARIFY", "澄清闭环及时率", "12%", "F-流程效率", "简道云[任务管理]"),
        ],
        "variables": [
            {"key": "project", "label": "项目/订单", "required": True, "placeholder": ""},
            {"key": "six_blocks", "label": "六块现状", "required": True, "placeholder": "文件|生产|检验|收款|澄清|发货"},
        ],
        "prompt_template": (
            "你是 V-FLO 项目跟单助理。按六块生成跟单摘要。\n项目：{{project}}\n现状：{{six_blocks}}\n\n"
            "输出：六块状态表（状态/卡点/责任人/下一步/截止日）；逾期预警；需升级事项。"
        ),
        "quality_notes": "六块状态齐全不遗漏；逾期项有预警与升级去向；下一步到人到日。",
        "example_input": "项目：VF-2026-066哈萨克泵站；六块：文件待批复|生产80%|检验未排|收款70%|澄清2项未关|发货待定",
        "example_output": "（六块状态表+逾期预警+需升级事项的项目会摘要）",
        "output_format": "table",
    },
    {
        "code": "SC-SAL-005", "title": "采购比价与交期催办", "department": "商务部", "category": "sales",
        "roles": "采购主管 / 商务专员-采购员",
        "timing": "定点前 / 交期临近",
        "goal": "比价结论或催交函",
        "default_model": "deepseek", "fallback_model": "mimo",
        "kpi_links": [
            K("KPI-SAL-04", "订单交付准时率", "7-18%", "V-价值创造", "简道云[订单交付]"),
            K("KPI-SAL-DOC", "文档与系统数据完整及时率", "8-10%", "O-优化创新", "简道云[内部资料]"),
        ],
        "variables": [
            {"key": "mode", "label": "用途", "required": True, "placeholder": "比价 / 催交"},
            {"key": "info", "label": "报价或订单信息", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是 V-FLO 采购助理。\n用途：{{mode}}\n信息：{{info}}\n\n"
            "若比价：输出比价表+总拥有成本+定点建议。若催交：输出对供方催交函+内部升级建议。"
            "涉及出口目的地物料时提示合规筛查。"
        ),
        "quality_notes": "比价须含总拥有成本与明确定点建议；催交函正式留痕并给内部升级路径；涉出口物料提示合规筛查。",
        "example_input": "用途：比价；信息：机械密封，A厂8.5万/12周，B厂7.9万/16周，C厂9.2万/10周含备件包",
        "example_output": "（比价表+总拥有成本+定点建议；或对供方催交函+内部升级建议）",
        "output_format": "table",
    },
    {
        "code": "SC-SAL-006", "title": "市场活动总结与业务洞察", "department": "商务部", "category": "sales",
        "roles": "国际销售主管 / 商务部经理",
        "timing": "展会/客户走访/线上活动后",
        "goal": "活动总结，支撑「业务洞察」AI评分",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-SAL-08", "业务洞察", "8-10%", "L-连接协同", "简道云[市场活动记录]"),
            K("KPI-SAL-03", "新增客户数", "10%", "V-价值创造", "简道云[CRM-客户]"),
        ],
        "variables": [
            {"key": "activity", "label": "活动", "required": True, "placeholder": ""},
            {"key": "notes", "label": "关键信息", "required": True, "placeholder": "客户反馈/竞争/价格/趋势"},
        ],
        "prompt_template": (
            "你是 V-FLO 市场分析师。写活动总结并输出业务洞察。\n活动：{{activity}}\n信息：{{notes}}\n\n"
            "输出：事实摘要—洞察（行业/竞争/客户）—线索转化建议—需沉淀知识库条目。洞察必须有证据支撑。"
        ),
        "quality_notes": "洞察必须有事实证据支撑；区分事实与推断；线索转化建议可执行。",
        "example_input": "活动：2026俄罗斯ECWATECH水处理展；信息：到访客户23家，竞品推新品，客户关注交期与售后",
        "example_output": "（事实摘要+行业/竞争/客户洞察+线索转化建议+入库条目建议）",
        "output_format": "markdown",
    },

    # ================= 工程技术部（前期） =================
    {
        "code": "SC-ENG-001", "title": "售前选型与方案对比", "department": "工程技术部（前期）", "category": "dev",
        "roles": "工程技术工程师 / 组长 / 主管",
        "timing": "询价技术响应阶段",
        "goal": "选型对比表+推荐配置，提升评审通过率",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-ENG-REVIEW", "设计评审通过率", "10-12%", "V-价值创造", "简道云[任务/评审]"),
            K("KPI-ENG-ONLINE", "项目按时完成率", "15-18%", "V-价值创造", "简道云[项目管理]"),
        ],
        "variables": [
            {"key": "duty_point", "label": "工况点", "required": True, "placeholder": "流量/扬程/介质/温度/压力"},
            {"key": "candidates", "label": "候选型号/厂家", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是 V-FLO 前期技术工程师，熟悉流程泵选型。\n工况：{{duty_point}}\n候选：{{candidates}}\n\n"
            "输出：工况理解；对比表（性能/材质/标准/交期/价格）；推荐与理由；需澄清问题。禁止编造性能曲线数据。"
        ),
        "quality_notes": "禁止编造性能曲线数据；推荐须给明确理由；不确定参数列入需澄清问题。",
        "example_input": "工况：Q=120m³/h，H=55m，含硫污水，80°C，1.6MPa；候选：ZE100-250/国产CHL/进口CR",
        "example_output": "（工况理解+候选对比表+推荐与理由+需澄清问题清单）",
        "output_format": "table",
    },
    {
        "code": "SC-ENG-002", "title": "报价成本核算表骨架", "department": "工程技术部（前期）", "category": "dev",
        "roles": "工程技术部主管 / 组长",
        "timing": "报价提交前",
        "goal": "成本结构与毛利测算骨架",
        "default_model": "deepseek", "fallback_model": "mimo",
        "kpi_links": [K("KPI-ENG-DOC", "文档记录完整度", "7-10%", "O-优化创新", "简道云[内部资料]")],
        "variables": [
            {"key": "bom", "label": "BOM/外购件要点", "required": True, "placeholder": ""},
            {"key": "target_margin", "label": "目标毛利", "required": False, "placeholder": "如：18%"},
        ],
        "prompt_template": (
            "你是成本核算助理。生成报价成本表骨架。\nBOM：{{bom}}\n目标毛利：{{target_margin}}\n\n"
            "输出：材料/加工/外购/包装运费/税费/毛利结构表；敏感项标注；定价建议。"
        ),
        "quality_notes": "成本分项齐全（材料/加工/外购/包装运费/税费/毛利）；敏感项有标注；不虚构单价。",
        "example_input": "BOM：泵体铸件2件/机封2套/电机2台/变频器1台；目标毛利：18%",
        "example_output": "（分项成本结构表+敏感项标注+定价建议的成本表骨架）",
        "output_format": "table",
    },
    {
        "code": "SC-ENG-003", "title": "需求解析与澄清问题清单", "department": "工程技术部（前期）", "category": "dev",
        "roles": "工程技术工程师",
        "timing": "收到标书/技术规格书后",
        "goal": "结构化需求+必须澄清项",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [K("KPI-ENG-ONLINE", "项目按时完成率", "15-18%", "V-价值创造", "简道云[项目管理]")],
        "variables": [{"key": "spec", "label": "规格书/标书片段", "required": True, "placeholder": ""}],
        "prompt_template": (
            "你是需求解析专家。\n内容：\n{{spec}}\n\n"
            "输出：项目信息表；关键参数表(规定值/单位/强制|推荐)；歧义项；必须澄清的问题（按优先级）。"
        ),
        "quality_notes": "关键参数须含规定值/单位/强制或推荐属性；歧义项单列；澄清问题按优先级排序。",
        "example_input": "规格书片段：泵须符合API610，NPSHr≤3m，过流件双相钢，文件须英文提交……",
        "example_output": "（项目信息表+关键参数表+歧义项+按优先级排序的澄清问题清单）",
        "output_format": "table",
    },

    # ================= 工程技术部（后期） =================
    {
        "code": "SC-ENG-011", "title": "交付文件清单与计划", "department": "工程技术部（后期）", "category": "dev",
        "roles": "后期经理 / 副经理 / 机械工程师-后期",
        "timing": "合同交接后 3 日内",
        "goal": "文件计划与澄清闭环机制",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-ENG-FILE", "技术文件编制数", "25%", "V-价值创造", "简道云[任务管理]"),
            K("KPI-ENG-ONLINE", "项目按时完成率", "30%", "V-价值创造", "简道云[项目管理]"),
        ],
        "variables": [
            {"key": "order", "label": "订单/项目", "required": True, "placeholder": ""},
            {"key": "req_docs", "label": "客户要求文件", "required": True, "placeholder": "数据表/GA/PID/手册等"},
        ],
        "prompt_template": (
            "你是后期交付工程师。生成交付文件清单与进度计划。\n订单：{{order}}\n要求文件：{{req_docs}}\n\n"
            "输出：文件清单表(编号/名称/责任人/提交日/状态)；澄清关闭规则(3工作日)；风险项。"
        ),
        "quality_notes": "文件清单到编号/责任人/提交日/状态；澄清关闭规则明确3个工作日。",
        "example_input": "订单：VF-2026-066；要求文件：数据表/GA图/PID/安装手册/材质证书，英文，批复制",
        "example_output": "（文件清单表+3工作日澄清关闭规则+风险项的交付计划）",
        "output_format": "table",
    },
    {
        "code": "SC-ENG-012", "title": "客户批复意见处理单", "department": "工程技术部（后期）", "category": "dev",
        "roles": "机械工程师-后期 / 三维",
        "timing": "收到客户批复后 3 个工作日内",
        "goal": "逐条处理意见并形成回复",
        "default_model": "mimo", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-ENG-FILE", "技术文件编制数", "25%", "V-价值创造", "简道云[任务管理]"),
            K("KPI-ENG-QUALITY", "工作完成质量(AI)", "5%", "L-连接协同", "简道云[任务管理-AI评分]"),
        ],
        "variables": [
            {"key": "comments", "label": "客户批复意见", "required": True, "placeholder": ""},
            {"key": "our_action", "label": "我方处理要点", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是后期文件工程师。生成批复处理单。\n意见：{{comments}}\n处理：{{our_action}}\n\n"
            "输出：逐条(意见/处理/是否修改文件/负责人/完成日)；需再次澄清项；版本升级提示。"
        ),
        "quality_notes": "逐条对应不遗漏；每条明确是否修改文件、负责人与完成日；需再澄清项单列。",
        "example_input": "客户意见：1.GA图补地脚螺栓尺寸 2.数据表材质改SS316；我方处理：1.三维修改后升版 2.与采购确认后回复",
        "example_output": "（逐条处理单：意见/处理/是否改文件/负责人/完成日+版本升级提示）",
        "output_format": "table",
    },
    {
        "code": "SC-ENG-013", "title": "三维模型修改说明", "department": "工程技术部（后期）", "category": "dev",
        "roles": "机械工程师-三维",
        "timing": "客户批复三维修改/新开模具核对",
        "goal": "修改说明与核对清单",
        "default_model": "deepseek", "fallback_model": "mimo",
        "kpi_links": [K("KPI-ENG-3D", "三维绘制/修改数量", "15-20%", "V-价值创造", "简道云[任务管理]")],
        "variables": [
            {"key": "change", "label": "修改内容", "required": True, "placeholder": ""},
            {"key": "parts", "label": "涉及零件", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是三维设计助理。生成修改说明与核对清单。\n修改：{{change}}\n零件：{{parts}}\n\n"
            "输出：修改项表；受影响图纸/BOM；核对清单；需设计确认项。"
        ),
        "quality_notes": "修改项与受影响图纸/BOM一一对应；核对清单可逐项打钩；不确定项标需设计确认。",
        "example_input": "修改：底座开孔距500改520，新增吊耳2个；零件：底座/泵盖/进出口法兰",
        "example_output": "（修改项表+受影响图纸/BOM清单+核对清单+需设计确认项）",
        "output_format": "table",
    },

    # ================= 屏蔽泵事业部 =================
    {
        "code": "SC-PMP-001", "title": "屏蔽泵选型与数据表", "department": "屏蔽泵事业部", "category": "dev",
        "roles": "机械工程师（屏蔽泵设计）",
        "timing": "客户询价/技术澄清",
        "goal": "选型建议+数据表骨架",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-PMP-FILE", "技术文件编制数", "20%", "V-价值创造", "简道云[任务管理]"),
            K("KPI-PMP-REVIEW", "设计评审通过率", "15%", "V-价值创造", "简道云[任务/评审]"),
        ],
        "variables": [
            {"key": "duty", "label": "工况", "required": True, "placeholder": "介质/流量/扬程/温度/压力/NPSH"},
            {"key": "std", "label": "执行标准", "required": False, "placeholder": "API685/ISO等"},
        ],
        "prompt_template": (
            "你是屏蔽泵设计工程师。给出选型建议与数据表骨架。\n工况：{{duty}}\n标准：{{std}}\n\n"
            "输出：选型逻辑；推荐型号特征；数据表字段骨架；需计算/确认项（水力/热力/电磁）。不编造曲线。"
        ),
        "quality_notes": "选型逻辑可追溯；数据表字段齐全；不编造曲线与性能数据，待计算/确认项显式列出。",
        "example_input": "工况：介质液氨，Q=25m³/h，H=80m，-33°C，NPSHa=2.5m；标准：API685",
        "example_output": "（选型逻辑+推荐型号特征+数据表字段骨架+需计算/确认项清单）",
        "output_format": "markdown",
    },
    {
        "code": "SC-PMP-002", "title": "设计计算书结构与校核清单", "department": "屏蔽泵事业部", "category": "dev",
        "roles": "机械工程师 / 技术副总 / 主管",
        "timing": "方案设计与详细设计阶段",
        "goal": "计算书目录+校核清单，提升评审通过率",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-PMP-REVIEW", "设计评审通过率", "15%", "V-价值创造", "简道云[任务/评审]"),
            K("KPI-PMP-TECH", "技术创新", "7-14%", "L-连接协同", "简道云[任务/知识库]"),
        ],
        "variables": [{"key": "design", "label": "设计对象与约束", "required": True, "placeholder": ""}],
        "prompt_template": (
            "你是屏蔽泵技术专家。输出计算书结构与校核清单。\n对象：{{design}}\n\n"
            "输出：水力/热力/转子动力学/电磁/强度章节骨架；校核项清单；评审关注点。"
        ),
        "quality_notes": "计算书章节覆盖水力/热力/转子动力学/电磁/强度；校核项可逐条检查；评审关注点明确。",
        "example_input": "设计对象：45kW屏蔽泵，输送LPG，防爆ExdIIBT4，380V",
        "example_output": "（五类计算章节骨架+校核项清单+评审关注点）",
        "output_format": "markdown",
    },

    # ================= 研发设计部 =================
    {
        "code": "SC-RND-001", "title": "研发项目计划与里程碑", "department": "研发设计部", "category": "dev",
        "roles": "研发设计经理 / 部门主管",
        "timing": "立项时 / 季度规划",
        "goal": "项目计划骨架，支撑研发项目完成数",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-RND-01", "研发项目完成数", "18-20%", "V-价值创造", "简道云[项目管理]"),
            K("KPI-RND-02", "设计评审通过率", "20%", "V-价值创造", "简道云[任务/评审]"),
        ],
        "variables": [
            {"key": "project", "label": "项目", "required": True, "placeholder": ""},
            {"key": "goals", "label": "目标", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是研发项目经理。生成项目计划骨架。\n项目：{{project}}\n目标：{{goals}}\n\n"
            "输出：WBS；里程碑；资源；风险；评审节点；与简道云任务字段对齐的建议（标题/起止/负责人/优先级/所属项目）。"
        ),
        "quality_notes": "WBS与里程碑完整；任务字段与简道云五要素对齐（标题/起止/负责人/优先级/所属项目）。",
        "example_input": "项目：高效屏蔽泵水力模型开发；目标：效率提升3%，2026Q4完成样机验证",
        "example_output": "（WBS+里程碑+资源+风险+评审节点+简道云字段建议的项目计划骨架）",
        "output_format": "markdown",
    },
    {
        "code": "SC-RND-002", "title": "NCR处置建议书", "department": "研发设计部", "category": "dev",
        "roles": "产品研发工程师 / 主管",
        "timing": "不合格品/NCR产生后",
        "goal": "处置建议与纠正预防",
        "default_model": "deepseek", "fallback_model": "mimo",
        "kpi_links": [
            K("KPI-RND-03", "NCR处置参与及时率", "10%", "V-价值创造", "简道云[任务管理]"),
            K("KPI-QUA-05", "流程改进项目数", "8-10%", "O-优化创新", "简道云[项目结项/意见箱]"),
        ],
        "variables": [
            {"key": "ncr", "label": "NCR事实", "required": True, "placeholder": ""},
            {"key": "cause", "label": "原因分析线索", "required": False, "placeholder": ""},
        ],
        "prompt_template": (
            "你是研发质量工程师。输出NCR处置建议。\n事实：{{ncr}}\n线索：{{cause}}\n\n"
            "输出：问题定义—原因假设—处置方案(返工/让步/报废)—纠正预防—需验证项。禁止编造检测数据。"
        ),
        "quality_notes": "处置方案三选一明确（返工/让步/报废）并有纠正预防；禁止编造检测数据；需验证项单列。",
        "example_input": "NCR事实：泵体铸件X光探伤2处气孔超标；线索：近期更换树脂砂供应商",
        "example_output": "（问题定义—原因假设—处置方案—纠正预防—需验证项的处置建议书）",
        "output_format": "markdown",
    },
    {
        "code": "SC-RND-003", "title": "BOM编制与变更单", "department": "研发设计部", "category": "dev",
        "roles": "ERP专员 / 产品研发工程师",
        "timing": "设计输出/变更时",
        "goal": "BOM变更单，支撑BOM编制与变更KPI",
        "default_model": "deepseek", "fallback_model": "mimo",
        "kpi_links": [K("KPI-RND-BOM", "BOM编制与变更", "25%", "V-价值创造", "简道云[任务管理]")],
        "variables": [
            {"key": "change", "label": "变更内容", "required": True, "placeholder": ""},
            {"key": "items", "label": "物料明细", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是BOM工程师。生成变更单。\n变更：{{change}}\n明细：{{items}}\n\n"
            "输出：变更原因；增删改物料表；受影响工单/采购；生效条件。"
        ),
        "quality_notes": "增删改物料逐项列明；受影响工单/采购全覆盖；生效条件明确。",
        "example_input": "变更：机封供应商由A改B；明细：删A-123机械密封2件，增B-456机械密封2件",
        "example_output": "（变更原因+增删改物料表+受影响工单/采购+生效条件的变更单）",
        "output_format": "table",
    },

    # ================= 生产部 =================
    {
        "code": "SC-PRD-001", "title": "生产日报/班组交接", "department": "生产部", "category": "general",
        "roles": "班组长 / 生产文员 / 生产助理",
        "timing": "每日下班前",
        "goal": "日报与异常升级，支撑任务完成数",
        "default_model": "mimo", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-PRD-01", "任务完成数", "8-15%", "V-价值创造", "简道云[任务管理]"),
            K("KPI-PRD-DOC", "文档记录完整度", "15%", "O-优化创新", "简道云[内部资料/任务附件]"),
        ],
        "variables": [
            {"key": "line", "label": "班组/产线", "required": True, "placeholder": ""},
            {"key": "output", "label": "完成情况", "required": True, "placeholder": ""},
            {"key": "issues", "label": "异常", "required": True, "placeholder": "无则写无"},
        ],
        "prompt_template": (
            "你是生产文员助理。生成生产日报。\n班组：{{line}}\n完成：{{output}}\n异常：{{issues}}\n\n"
            "输出：产量/进度表；异常与处理；需协调；明日计划。可直接作为简道云任务附件。"
        ),
        "quality_notes": "产量/进度如实填写；异常有处理与升级去向；可直接作为简道云任务附件。",
        "example_input": "班组：装配一班；完成：屏蔽泵装配3台，计划达成100%；异常：1台电机到货延迟，已报采购",
        "example_output": "（产量进度表+异常与处理+需协调+明日计划的日报）",
        "output_format": "markdown",
    },
    {
        "code": "SC-PRD-002", "title": "设备点检与故障报修单", "department": "生产部", "category": "general",
        "roles": "电工 / 班组长 / 技术支持",
        "timing": "点检异常/设备故障时",
        "goal": "报修单规范留痕",
        "default_model": "mimo", "fallback_model": "deepseek",
        "kpi_links": [K("KPI-PRD-SAFE", "安全事故次数", "15%", "V-价值创造", "简道云/安全记录")],
        "variables": [
            {"key": "equipment", "label": "设备", "required": True, "placeholder": ""},
            {"key": "symptom", "label": "现象", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是设备维修助理。生成报修/点检单。\n设备：{{equipment}}\n现象：{{symptom}}\n\n"
            "输出：现象描述；可能原因；应急措施；安全提示；报修升级建议。"
        ),
        "quality_notes": "现象描述具体可定位；应急措施与安全提示明确；报修升级建议到层级。",
        "example_input": "设备：2号数控车床；现象：主轴异响，800转以上明显，伴振动",
        "example_output": "（现象描述+可能原因+应急措施+安全提示+升级建议的报修单）",
        "output_format": "document",
    },
    {
        "code": "SC-PRD-003", "title": "工艺/作业指导要点卡", "department": "生产部", "category": "general",
        "roles": "生产部长 / 技术支持 / 班组长",
        "timing": "新工艺导入/培训时",
        "goal": "SOP要点卡，支撑流程改进",
        "default_model": "deepseek", "fallback_model": "mimo",
        "kpi_links": [K("KPI-PRD-IMP", "流程改进项目数", "10%", "O-优化创新", "简道云[项目结项]")],
        "variables": [{"key": "process", "label": "工序", "required": True, "placeholder": ""}],
        "prompt_template": (
            "你是工艺工程师。输出作业要点卡。\n工序：{{process}}\n\n"
            "输出：目的/适用范围/步骤/质量控制点/安全要点/常见异常处理。"
        ),
        "quality_notes": "步骤可操作；质量控制点与安全要点明确；常见异常有处理指引。",
        "example_input": "工序：屏蔽泵定子屏蔽套氩弧焊",
        "example_output": "（目的/适用范围/步骤/质量控制点/安全要点/常见异常处理的作业要点卡）",
        "output_format": "document",
    },

    # ================= 质检部 =================
    {
        "code": "SC-QA-001", "title": "8D/质量问题报告初稿", "department": "质检部", "category": "general",
        "roles": "质检部部长 / 主管 / 机械工程师QA",
        "timing": "客户投诉/批量不合格",
        "goal": "8D报告初稿",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-QA-01", "质量合格率", "18-20%", "V-价值创造", "简道云[质量记录]"),
            K("KPI-QA-02", "不良率", "10-15%", "V-价值创造", "简道云[质量记录]"),
            K("KPI-QA-03", "客户投诉次数", "8%", "F-流程效率", "简道云[跟进记录]"),
        ],
        "variables": [
            {"key": "problem", "label": "问题描述", "required": True, "placeholder": ""},
            {"key": "containment", "label": "围堵措施", "required": False, "placeholder": ""},
            {"key": "analysis", "label": "原因线索", "required": False, "placeholder": ""},
        ],
        "prompt_template": (
            "你是质量工程师，编写8D报告。\n问题：{{problem}}\n围堵：{{containment}}\n分析：{{analysis}}\n\n"
            "输出完整8D(D1-D8)，未知写“待补充”，禁止编造根因与检测数据。"
        ),
        "quality_notes": "D1–D8完整；未知项写“待补充”；禁止编造根因与检测数据。",
        "example_input": "问题：客户反馈泵运行2周后机封泄漏，批次2026-08；围堵：同批次库存封存复检；分析：疑似O圈材质不耐介质",
        "example_output": "（D1–D8完整的8D报告初稿，未知项标注待补充）",
        "output_format": "markdown",
    },
    {
        "code": "SC-QA-002", "title": "质量月报/质量分析会材料", "department": "质检部", "category": "general",
        "roles": "质检部部长 / 主管",
        "timing": "每月质量分析会前",
        "goal": "数据驱动的改进提案",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-QA-IMP", "流程改进项目数", "8-10%", "O-优化创新", "简道云[项目结项/意见箱]"),
            K("KPI-QA-DOC", "文档记录完整度", "10-15%", "O-优化创新", "简道云[内部资料]"),
        ],
        "variables": [
            {"key": "data", "label": "质量数据", "required": True, "placeholder": "合格率/不良/投诉/NCR"},
        ],
        "prompt_template": (
            "你是质量分析助理。生成质量月报。\n数据：{{data}}\n\n"
            "输出：指标趋势；帕累托不良项；根因假设；改进项目建议(可进简道云项目结项)；下月目标。"
        ),
        "quality_notes": "指标趋势基于所给数据；帕累托排序正确；改进项目建议可落地并可进简道云结项。",
        "example_input": "质量数据：9月合格率98.2%，不良TOP3为气孔/尺寸超差/泄漏，客诉1起，NCR4份",
        "example_output": "（指标趋势+帕累托不良项+根因假设+改进项目建议+下月目标的月报）",
        "output_format": "markdown",
    },
    {
        "code": "SC-QA-003", "title": "检验记录规范填写助手", "department": "质检部", "category": "general",
        "roles": "质检员QC / 机械工程师QA",
        "timing": "检验过程中",
        "goal": "记录完整，降低合规事件",
        "default_model": "mimo", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-QA-DOC", "文档记录完整度", "15%", "O-优化创新", "简道云[内部资料]"),
            K("KPI-QA-COMP", "合规事件次数", "8-15%", "F-流程效率", "简道云[意见箱]"),
        ],
        "variables": [
            {"key": "inspection", "label": "检验项目与结果", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是质检记录助理。整理检验记录。\n内容：{{inspection}}\n\n"
            "输出：规范记录条目（项目/标准/实测/判定/检验员/时间）；缺项提醒；异常升级建议。"
        ),
        "quality_notes": "记录条目齐全（项目/标准/实测/判定/检验员/时间）；缺项有提醒；异常有升级建议。",
        "example_input": "检验项目：泵体水压试验，1.5倍设计压力保压10min，实测无渗漏，检验员王五",
        "example_output": "（规范检验记录条目+缺项提醒+异常升级建议）",
        "output_format": "table",
    },

    # ================= 财务部 =================
    {
        "code": "SC-FIN-001", "title": "财务报表编制检查单", "department": "财务部", "category": "general",
        "roles": "财务经理 / 会计 / 财务主管会计",
        "timing": "月/季结账前",
        "goal": "检查单，提升报表及时率",
        "default_model": "deepseek", "fallback_model": "mimo",
        "kpi_links": [
            K("KPI-FIN-01", "财务报表出具及时率", "15-18%", "V-价值创造", "简道云[开票/回款]"),
            K("KPI-FIN-03", "凭证差错次数", "15-20%", "V-价值创造", "简道云[付款/回款单]"),
        ],
        "variables": [
            {"key": "period", "label": "期间", "required": True, "placeholder": "2026-09"},
            {"key": "status", "label": "结账进度", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是结账助理。生成报表编制检查单。\n期间：{{period}}\n进度：{{status}}\n\n"
            "输出：结账步骤检查单；常见差错点；未完成项责任人；出具时间倒排。不涉及具体金额编造。"
        ),
        "quality_notes": "检查单覆盖结账全步骤；常见差错点列明；不编造具体金额；出具时间倒排到日。",
        "example_input": "期间：2026-09；进度：凭证录入90%，银行对账完成，折旧未计提，出口退税待申报",
        "example_output": "（结账步骤检查单+常见差错点+未完成项责任人+出具时间倒排）",
        "output_format": "table",
    },
    {
        "code": "SC-FIN-002", "title": "税务申报提醒与资料清单", "department": "财务部", "category": "general",
        "roles": "会计 / 财务经理",
        "timing": "征期前",
        "goal": "申报清单，降低合规事件",
        "default_model": "mimo", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-FIN-02", "报税及时率", "10-12%", "V-价值创造", "简道云[开票]"),
            K("KPI-FIN-COMP", "合规事件次数", "10%", "F-流程效率", "简道云[意见箱]"),
        ],
        "variables": [
            {"key": "taxes", "label": "涉及税种与公司", "required": True, "placeholder": "13家公司/增值税/个税/出口退税等"},
        ],
        "prompt_template": (
            "你是税务助理。生成申报提醒清单。\n范围：{{taxes}}\n\n"
            "输出：税种/征期/资料清单/责任人/风险提示。含出口退税进程跟踪提醒。"
        ),
        "quality_notes": "税种/征期/资料/责任人四要素齐全；含出口退税进程跟踪提醒；风险提示具体。",
        "example_input": "范围：集团13家公司，增值税/企业所得税/个税/出口退税",
        "example_output": "（税种/征期/资料清单/责任人/风险提示的申报提醒清单）",
        "output_format": "table",
    },
    {
        "code": "SC-FIN-003", "title": "费用报销初审要点", "department": "财务部", "category": "general",
        "roles": "出纳 / 会计",
        "timing": "报销单据到达时",
        "goal": "初审清单，降差错",
        "default_model": "mimo", "fallback_model": "deepseek",
        "kpi_links": [K("KPI-FIN-03", "凭证差错次数", "15-20%", "V-价值创造", "简道云[付款单]")],
        "variables": [{"key": "expense", "label": "报销事由与单据", "required": True, "placeholder": ""}],
        "prompt_template": (
            "你是报销初审助理。\n内容：{{expense}}\n\n"
            "输出：合规性检查清单（发票/审批/标准/附件）；退回补正项；可入账摘要建议。"
        ),
        "quality_notes": "合规检查覆盖发票/审批/标准/附件；退回补正项明确；摘要建议可直接入账。",
        "example_input": "报销事由：莫斯科展会差旅费，机票+酒店发票3张合计2.1万，已附审批单",
        "example_output": "（合规性检查清单+退回补正项+可入账摘要建议）",
        "output_format": "table",
    },

    # ================= 人事行政部 =================
    {
        "code": "SC-HR-001", "title": "招聘岗位说明书与面试题", "department": "人事行政部", "category": "general",
        "roles": "人事主管 / 人事行政专员 / 人事行政经理",
        "timing": "启动招聘时",
        "goal": "JD+面试题，支撑招聘完成数",
        "default_model": "kimi", "fallback_model": "mimo",
        "kpi_links": [
            K("KPI-HR-01", "招聘完成数", "15-20%", "V-价值创造", "简道云[任务-招聘类]"),
            K("KPI-HR-03", "人才储备完成度", "10-12%", "O-优化创新", "简道云[任务-人才储备]"),
        ],
        "variables": [
            {"key": "position", "label": "岗位", "required": True, "placeholder": ""},
            {"key": "dept", "label": "部门", "required": True, "placeholder": ""},
            {"key": "must", "label": "硬性要求", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是 HR 专家。生成岗位说明书与结构化面试题。\n岗位：{{position}}\n部门：{{dept}}\n要求：{{must}}\n\n"
            "输出：JD；任职资格；面试评价表(与四维绩效对齐)；5道结构化面试题与评分要点。"
        ),
        "quality_notes": "JD与硬性要求一致；面试题结构化且附评分要点；评价表与四维绩效对齐。",
        "example_input": "岗位：国际销售；部门：商务部；硬性要求：英语流利、俄语优先，3年泵阀外贸经验",
        "example_output": "（JD+任职资格+面试评价表+5道结构化面试题与评分要点）",
        "output_format": "document",
    },
    {
        "code": "SC-HR-002", "title": "培训纪要与学时统计", "department": "人事行政部", "category": "general",
        "roles": "人事行政专员 / 人事主管",
        "timing": "培训结束后当天",
        "goal": "纪要+学时，支撑培训完成学时",
        "default_model": "mimo", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-HR-02", "培训完成学时", "10-15%", "V-价值创造", "简道云[任务-培训类/预计工时]"),
            K("KPI-HR-DOC", "文档记录完整度", "10-15%", "O-优化创新", "简道云[内部资料]"),
        ],
        "variables": [
            {"key": "training", "label": "培训主题", "required": True, "placeholder": ""},
            {"key": "attendees", "label": "参加人与学时", "required": True, "placeholder": ""},
            {"key": "points", "label": "要点", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是培训助理。生成培训纪要。\n主题：{{training}}\n参加：{{attendees}}\n要点：{{points}}\n\n"
            "输出：纪要；学时统计表(可直接录简道云预计工时)；效果评估；后续行动。"
        ),
        "quality_notes": "学时统计可直接录简道云预计工时；纪要含效果评估与后续行动。",
        "example_input": "主题：出口管制合规培训；参加：销售/项目共18人，每人2学时；要点：红旗识别/EUC/制裁名单",
        "example_output": "（培训纪要+学时统计表+效果评估+后续行动）",
        "output_format": "markdown",
    },
    {
        "code": "SC-HR-003", "title": "绩效面谈提纲与改进计划", "department": "人事行政部", "category": "general",
        "roles": "人事行政经理 / 人事主管 / 各部门负责人",
        "timing": "季度绩效周期",
        "goal": "面谈提纲+改进计划，支撑团队培养与360",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-HR-TEAM", "团队培养达成度", "10%", "F-流程效率", "简道云[任务-团队培养]"),
            K("KPI-HR-360", "360度评估", "10-12%", "L-连接协同", "简道云[任务-评估分值]"),
            K("KPI-HR-MENTOR", "导师带教", "7-8%", "L-连接协同", "简道云[任务-导师带教]"),
        ],
        "variables": [
            {"key": "role", "label": "被面谈人岗位", "required": True, "placeholder": ""},
            {"key": "facts", "label": "事实依据", "required": True, "placeholder": "任务完成/质量/协作"},
        ],
        "prompt_template": (
            "你是绩效教练。生成面谈提纲与改进计划。\n岗位：{{role}}\n事实：{{facts}}\n\n"
            "输出：面谈结构(成绩/不足/倾听/目标)；改进计划表(目标/行动/资源/节点)；可录入简道云的团队培养任务建议。"
        ),
        "quality_notes": "面谈基于事实依据；改进计划表到目标/行动/资源/节点；建议可录简道云团队培养任务。",
        "example_input": "岗位：项目工程师；事实：季度任务完成12/14，1次周报迟交，获客户表扬信1封",
        "example_output": "（面谈结构提纲+改进计划表+可录简道云的团队培养任务建议）",
        "output_format": "markdown",
    },
    {
        "code": "SC-HR-004", "title": "制度通知与活动方案", "department": "人事行政部", "category": "general",
        "roles": "人事行政专员 / 经理",
        "timing": "发布制度/年会团建/检查通知",
        "goal": "正式公文",
        "default_model": "mimo", "fallback_model": "kimi",
        "kpi_links": [K("KPI-HR-IMP", "流程改进项目数", "10%", "O-优化创新", "简道云[项目结项/意见箱]")],
        "variables": [
            {"key": "topic", "label": "主题", "required": True, "placeholder": ""},
            {"key": "points", "label": "要点", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是行政文秘。撰写正式通知/方案。\n主题：{{topic}}\n要点：{{points}}\n\n"
            "输出：标题—背景—要求—时间—责任—落款。语气庄重清晰。"
        ),
        "quality_notes": "公文要素齐全（标题/背景/要求/时间/责任/落款）；语气庄重清晰无歧义。",
        "example_input": "主题：2026年中秋国庆放假通知；要点：放假8天、值班安排、节前安全检查",
        "example_output": "（标题—背景—要求—时间—责任—落款的正式通知）",
        "output_format": "document",
    },

    # ================= 总经办 =================
    {
        "code": "SC-GM-001", "title": "经营分析一页纸", "department": "总经办", "category": "general",
        "roles": "总经理 / 常务副总 / 营销副总 / 技术副总",
        "timing": "月度经营会前",
        "goal": "决策就绪的经营摘要",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-GM-01", "销售额/回款额", "15-20%", "V-价值创造", "简道云[CRM-订单/回款]"),
            K("KPI-GM-DECIDE", "决策质量", "15%", "L-连接协同", "简道云[任务-决策评审/AI评分]"),
            K("KPI-GM-INSIGHT", "业务洞察", "10-12%", "L-连接协同", "简道云[市场活动/线索]"),
        ],
        "variables": [
            {"key": "period", "label": "期间", "required": True, "placeholder": ""},
            {"key": "data", "label": "经营数据要点", "required": True, "placeholder": "销售/回款/交付/质量/人效"},
            {"key": "issues", "label": "重大议题", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是集团经营分析助理。生成一页经营分析。\n期间：{{period}}\n数据：{{data}}\n议题：{{issues}}\n\n"
            "输出：结论先行；关键指标红黄绿；问题根因假设；决策选项(利弊/风险/建议)；下周动作。"
            "要求体现决策质量与业务洞察，供AI评分与会议使用。"
        ),
        "quality_notes": "结论先行；指标红黄绿基于数据；决策选项含利弊/风险/建议，体现决策质量与业务洞察。",
        "example_input": "期间：2026-09；数据：销售800万/回款620万/交付准时率92%/客诉2起；议题：俄市场付款延迟、新品上市节奏",
        "example_output": "（结论先行的一页纸：红黄绿指标+根因假设+决策选项+下周动作）",
        "output_format": "markdown",
    },
    {
        "code": "SC-GM-002", "title": "战略任务分解与督办清单", "department": "总经办", "category": "general",
        "roles": "总经理 / 常务副总",
        "timing": "季度/半年度战略部署后",
        "goal": "战略任务落到简道云可考核",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-GM-STRAT", "战略执行力", "15%", "L-连接协同", "简道云[任务-战略任务/AI评分]"),
            K("KPI-GM-IMP", "流程改进项目数", "10%", "O-优化创新", "简道云[项目结项]"),
        ],
        "variables": [
            {"key": "strategy", "label": "战略要点", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是战略执行助理。分解战略任务。\n要点：{{strategy}}\n\n"
            "输出：任务分解表(任务名/负责人/部门/起止/优先级/所属项目/验收标准)；"
            "可直接录入简道云任务管理；督办节奏建议。"
        ),
        "quality_notes": "任务分解含任务名/负责人/部门/起止/优先级/所属项目/验收标准，可直接录简道云；督办节奏明确。",
        "example_input": "战略要点：2026年海外营收占比提至40%，重点突破中亚市场",
        "example_output": "（可直接录简道云的任务分解表+督办节奏建议）",
        "output_format": "table",
    },
    {
        "code": "SC-GM-003", "title": "重大决策评审材料", "department": "总经办", "category": "general",
        "roles": "总经理 / 副总经理",
        "timing": "重大投资/投标/人事/技术路线决策前",
        "goal": "结构化决策材料",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [K("KPI-GM-DECIDE", "决策质量", "15%", "L-连接协同", "简道云[任务-决策评审]")],
        "variables": [
            {"key": "decision", "label": "决策事项", "required": True, "placeholder": ""},
            {"key": "options", "label": "候选方案", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是决策参谋。生成决策评审材料。\n事项：{{decision}}\n方案：{{options}}\n\n"
            "输出：背景；方案对比(收益/风险/资源/周期)；敏感性；建议与触发回滚条件；需董事会/合规审批项。"
        ),
        "quality_notes": "方案对比含收益/风险/资源/周期；有敏感性分析与回滚触发条件；需审批项明确。",
        "example_input": "决策事项：是否在哈萨克设装配点；候选方案：A独资建厂/B与本地代理合作/C维持直接出口",
        "example_output": "（背景+方案对比+敏感性+建议与回滚条件+需审批项的评审材料）",
        "output_format": "document",
    },

    # ================= 威标部（AI） =================
    {
        "code": "SC-AI-001", "title": "智能体需求任务书（简道云字段对齐）", "department": "威标部", "category": "dev",
        "roles": "AI开发工程师",
        "timing": "各部门提出智能体需求后",
        "goal": "可录入简道云的任务书，提升任务规划完整度",
        "default_model": "deepseek", "fallback_model": "kimi",
        "kpi_links": [
            K("KPI-AI-PLAN", "任务规划完整度", "8%", "O-优化创新", "简道云[任务-五要素完整]"),
            K("KPI-AI-01", "任务完成率", "12%", "V-价值创造", "简道云[任务管理]"),
            K("KPI-AI-04", "智能体开发项目参与数", "8%", "V-价值创造", "简道云[关联项目]"),
        ],
        "variables": [
            {"key": "request", "label": "业务需求描述", "required": True, "placeholder": ""},
            {"key": "dept", "label": "需求部门/岗位", "required": True, "placeholder": ""},
            {"key": "deadline", "label": "期望完成时间", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是 AI 产品经理。生成智能体开发任务书。\n需求：{{request}}\n部门：{{dept}}\n期望：{{deadline}}\n\n"
            "输出必须包含简道云任务五要素：任务标题、开始时间、截止时间、负责人、优先级、所属项目；"
            "另加：验收标准、输入输出、依赖、风险。禁止空泛描述。"
        ),
        "quality_notes": "必须含简道云任务五要素（标题/起止/负责人/优先级/所属项目）；验收标准可勾选；禁止空泛描述。",
        "example_input": "需求：自动生成项目周报的智能体；部门：项目部/项目工程师；期望：2026-10-15前上线",
        "example_output": "（五要素+验收标准+输入输出+依赖+风险的开发任务书）",
        "output_format": "document",
    },
    {
        "code": "SC-AI-002", "title": "代码审查要点（工作质量AI评分）", "department": "威标部", "category": "dev",
        "roles": "AI开发工程师",
        "timing": "合并请求/阶段评审",
        "goal": "审查意见体现技术深度与可维护性",
        "default_model": "deepseek", "fallback_model": "mimo",
        "kpi_links": [
            K("KPI-AI-QUALITY", "工作完成质量(AI)", "10%", "L-连接协同", "简道云[任务-AI评分]"),
            K("KPI-AI-DOC", "知识沉淀与主动性(AI)", "10%", "L-连接协同", "简道云[知识库]"),
        ],
        "variables": [
            {"key": "summary", "label": "变更摘要", "required": True, "placeholder": ""},
            {"key": "diff_desc", "label": "关键实现/问题", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是资深工程师做代码审查。输出审查意见。\n变更：{{summary}}\n实现：{{diff_desc}}\n\n"
            "输出按严重度分级（阻断/建议/讨论），覆盖：正确性、安全、可维护性、测试、性能；"
            "结论明确是否可合并。文风体现技术深度（利于AI评分）。"
        ),
        "quality_notes": "意见按阻断/建议/讨论分级；覆盖正确性/安全/可维护性/测试/性能；结论明确是否可合并。",
        "example_input": "变更摘要：新增周报生成API；实现：router+service两层，含模型调用与缓存",
        "example_output": "（按严重度分级的审查意见+是否可合并的明确结论）",
        "output_format": "markdown",
    },
    {
        "code": "SC-AI-003", "title": "任务描述润色（拉高AI评分）", "department": "通用", "category": "general",
        "roles": "全员（写简道云任务的人）",
        "timing": "创建/更新简道云任务前",
        "goal": "高质量任务描述，直接改善「工作完成质量(AI)」得分",
        "default_model": "mimo", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-AI-QUALITY", "工作完成质量(AI)", "5-16%", "L-连接协同", "简道云[任务-AI评分]"),
            K("KPI-AI-PLAN", "任务规划完整度", "8%", "O-优化创新", "简道云[任务五要素]"),
        ],
        "variables": [
            {"key": "raw", "label": "口语化任务描述", "required": True, "placeholder": "随便写，我来帮你规范化"},
            {"key": "role", "label": "你的岗位", "required": False, "placeholder": ""},
        ],
        "prompt_template": (
            "你是简道云任务写作教练。把口语任务描述改成高分任务记录。\n"
            "岗位：{{role}}\n原文：{{raw}}\n\n"
            "改写规则（对应AI评分维度）：\n"
            "1) 技术深度：写清方法/标准/工具，不写“处理一下”；\n"
            "2) 问题解决彻底性：写清根因与验证，不写“已完成”；\n"
            "3) 方案可维护性：写清文档/模板/知识库去向。\n"
            "另输出：任务五要素建议（标题/起止/负责人/优先级/所属项目）与3条验收标准。"
        ),
        "quality_notes": "改写后必须比原文更具体、可验证、可复用。",
        "example_input": "原文：上周把客户那个图改了一下发出去了；岗位：机械工程师-后期",
        "example_output": "（体现技术深度/彻底性/可维护性的规范任务描述+五要素建议+3条验收标准）",
        "output_format": "markdown",
    },

    # ================= 出口管制合规（跨部门执行） =================
    {
        "code": "SC-EXP-001", "title": "出口管制初筛申请单", "department": "商务部", "category": "sales",
        "roles": "国际销售 / 项目跟单 / 采购主管 / 商务部经理",
        "timing": "新客户/新订单/新目的地/敏感物项前（签约前强制）",
        "goal": "生成合规审查单：两用物项重点分类 + 西方制裁目的地人工审核放行",
        "default_model": "deepseek", "fallback_model": "kimi",
        "security_level": "export_control",
        "kpi_links": [
            K("KPI-COMP-01", "合规事件次数", "7-10%", "F-流程效率", "简道云[意见箱]"),
            K("KPI-SAL-REVIEW", "商务条款审核质量", "15%", "O-优化创新", "简道云/评审记录"),
        ],
        "variables": [
            {"key": "customer", "label": "客户名称", "required": True, "placeholder": ""},
            {"key": "country", "label": "目的地/最终用户所在国", "required": True, "placeholder": "中文或ISO代码"},
            {"key": "end_user", "label": "最终用户", "required": False, "placeholder": "与客户不同必填"},
            {"key": "end_use", "label": "最终用途", "required": True, "placeholder": "民用/工业/其他"},
            {"key": "product", "label": "产品描述", "required": True, "placeholder": "屏蔽泵/密封/变频等"},
        ],
        "prompt_template": (
            "你是 V-FLO 出口管制合规助理（终审权在合规官）。\n"
            "客户：{{customer}}\n国别：{{country}}\n最终用户：{{end_user}}\n最终用途：{{end_use}}\n产品：{{product}}\n\n"
            "V-FLO 政策要点：\n"
            "- 西方单边制裁目的地不自动拒绝，一律「人工审核放行」；\n"
            "- 重点把关两用物项/敏感物项，对照《中国两用物项出口管制清单》分类；\n"
            "- 仅大规模杀伤性武器/军用用途+受控物项才硬性禁止。\n\n"
            "输出：\n1. 检查清单状态\n2. 国家风险提示（含西方名单，仅提示）\n"
            "3. 物项分类提示（民用/工业两用/核/生化/导弹/军品）与是否需许可\n"
            "4. 红旗清单\n5. 结论：完成清单后放行 / 人工审核放行 / 升级分类 / 硬性禁止\n"
            "6. 后续动作与需补材料\n禁止提供规避任何适用法规的建议。不确定处标[待合规确认]。"
        ),
        "quality_notes": "结论四选一明确（放行/人工审核/升级分类/硬性禁止）；两用物项分类有依据；不确定处标[待合规确认]；不提供规避建议。",
        "example_input": "客户：ABC Trading LLP；国别：哈萨克斯坦；最终用户：同客户；用途：石化厂民用注水；产品：屏蔽泵2台",
        "example_output": "（检查清单+国家风险提示+物项分类+红旗清单+四选一结论+后续动作的审查单）",
        "output_format": "document",
    },
    {
        "code": "SC-EXP-002", "title": "最终用户/最终用途承诺书（EUC）起草", "department": "商务部", "category": "sales",
        "roles": "国际销售主管 / 商务部经理",
        "timing": "出口管制审查通过前",
        "goal": "中英双语EUC草稿",
        "default_model": "kimi", "fallback_model": "deepseek",
        "security_level": "export_control",
        "kpi_links": [K("KPI-COMP-01", "合规事件次数", "7-10%", "F-流程效率", "简道云[意见箱]")],
        "variables": [
            {"key": "parties", "label": "双方主体", "required": True, "placeholder": ""},
            {"key": "product", "label": "物项", "required": True, "placeholder": ""},
            {"key": "end_use", "label": "最终用途", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是国际贸易合规文秘。起草中英双语最终用户/最终用途声明（EUC）草稿。\n"
            "主体：{{parties}}\n物项：{{product}}\n用途：{{end_use}}\n\n"
            "输出：声明正文（不转让、不改用途、接受核查、违约责任）；签署栏；附件清单。"
            "注明需合规官/法务审定后使用。"
        ),
        "quality_notes": "中英双语对照；含不转让/不改用途/接受核查/违约责任条款；注明需合规官/法务审定后使用。",
        "example_input": "主体：V-FLO与ABC Trading LLP；物项：屏蔽泵2台及备件；用途：石化注水泵站民用",
        "example_output": "（中英双语EUC草稿：声明正文+签署栏+附件清单）",
        "output_format": "document",
    },
    {
        "code": "SC-EXP-003", "title": "出口管制与制裁条款审查", "department": "商务部", "category": "sales",
        "roles": "商务部经理 / 国际销售主管",
        "timing": "合同/代理协议/投标文件定稿前",
        "goal": "条款覆盖检查表",
        "default_model": "deepseek", "fallback_model": "kimi",
        "security_level": "export_control",
        "kpi_links": [K("KPI-COMP-01", "合规事件次数", "7-10%", "F-流程效率", "简道云[意见箱]")],
        "variables": [{"key": "clauses", "label": "现有条款", "required": True, "placeholder": ""}],
        "prompt_template": (
            "你是出口合规条款审查助理。\n条款：\n{{clauses}}\n\n"
            "输出：是否覆盖（出口许可、再出口、最终用途、制裁、审计配合、终止权）；缺口；建议补充条款。"
        ),
        "quality_notes": "六项覆盖逐一判定（许可/再出口/最终用途/制裁/审计配合/终止权）；缺口给出具体补充条款建议。",
        "example_input": "现有条款：买方承诺遵守适用法律；争议提交新加坡仲裁；无出口管制专项条款",
        "example_output": "（六项覆盖检查表+缺口清单+建议补充条款）",
        "output_format": "table",
    },
    {
        "code": "SC-EXP-004", "title": "技术资料外发合规边界确认", "department": "工程技术部（前期）", "category": "dev",
        "roles": "工程技术部主管 / 经理 / 项目工程师",
        "timing": "对外发送图纸、数据表、模型、手册前",
        "goal": "判断是否构成技术出口，给出外发边界",
        "default_model": "deepseek", "fallback_model": "kimi",
        "security_level": "export_control",
        "kpi_links": [
            K("KPI-COMP-01", "合规事件次数", "7-10%", "F-流程效率", "简道云[意见箱]"),
            K("KPI-ENG-DOC", "文档记录完整度", "7-10%", "O-优化创新", "简道云[内部资料]"),
        ],
        "variables": [
            {"key": "docs", "label": "拟外发资料清单", "required": True, "placeholder": "GA/PID/3D/计算书/源码"},
            {"key": "recipient", "label": "接收方", "required": True, "placeholder": "客户/代理/供应商/境外关联方"},
            {"key": "purpose", "label": "用途", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是技术出口合规助理。\n资料：{{docs}}\n接收方：{{recipient}}\n用途：{{purpose}}\n\n"
            "输出：逐项判断（公开/内部/可能受控）；脱敏与裁剪建议；需审批层级；"
            "禁止输出受控技术参数本身。结论仅供合规官决策。"
        ),
        "quality_notes": "逐项判断公开/内部/可能受控；不输出受控技术参数本身；审批层级明确。",
        "example_input": "资料：GA图/PID/3D模型/安装手册；接收方：哈萨克客户；用途：基础设计审查",
        "example_output": "（逐项受控判断表+脱敏裁剪建议+审批层级+合规官决策提示）",
        "output_format": "table",
    },
    {
        "code": "SC-EXP-005", "title": "红旗识别与升级报告", "department": "商务部", "category": "sales",
        "roles": "全体涉外岗位",
        "timing": "出现异常交易信号时",
        "goal": "红旗报告，强制升级",
        "default_model": "mimo", "fallback_model": "deepseek",
        "security_level": "export_control",
        "kpi_links": [K("KPI-COMP-01", "合规事件次数", "7-10%", "F-流程效率", "简道云[意见箱]")],
        "variables": [
            {"key": "facts", "label": "异常事实", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是出口管制红旗识别助手。\n事实：{{facts}}\n\n"
            "输出：红旗命中项；风险等级；必须停止的动作；升级对象与时限；需保存的证据清单。\n"
            "不得建议如何规避监管。"
        ),
        "quality_notes": "红旗命中项引用事实；风险等级明确；停止动作与升级对象/时限具体；附证据清单；不提供规避监管建议。",
        "example_input": "异常事实：新客户要求经第三国转运，拒绝透露最终用户，付款方为壳公司",
        "example_output": "（红旗命中项+风险等级+必须停止动作+升级对象与时限+证据清单的报告）",
        "output_format": "markdown",
    },
    {
        "code": "SC-EXP-006", "title": "合规培训要点与测验", "department": "人事行政部", "category": "general",
        "roles": "人事行政经理 / 人事主管",
        "timing": "年度合规培训 / 新员工入职",
        "goal": "培训材料与测验，降低合规事件",
        "default_model": "kimi", "fallback_model": "mimo",
        "security_level": "export_control",
        "kpi_links": [
            K("KPI-HR-02", "培训完成学时", "10%", "V-价值创造", "简道云[培训类任务]"),
            K("KPI-COMP-01", "合规事件次数", "8%", "F-流程效率", "简道云[意见箱]"),
        ],
        "variables": [
            {"key": "audience", "label": "培训对象", "required": True, "placeholder": "销售/项目/技术/全员"},
        ],
        "prompt_template": (
            "你是合规培训设计师。生成培训要点与测验。\n对象：{{audience}}\n\n"
            "输出：10条必会规则；3个V-FLO场景案例（可匿名）；5道测验题与答案；培训学时建议。"
        ),
        "quality_notes": "必会规则与V-FLO场景贴合；测验题附答案；学时建议合理可录简道云。",
        "example_input": "培训对象：销售与项目岗位",
        "example_output": "（10条必会规则+3个场景案例+5道测验题与答案+学时建议）",
        "output_format": "markdown",
    },

    # ================= 通用办公 =================
    {
        "code": "SC-GEN-001", "title": "邮件起草与润色", "department": "通用", "category": "general",
        "roles": "全员", "timing": "日常", "goal": "得体邮件",
        "default_model": "mimo", "fallback_model": "kimi",
        "kpi_links": [K("KPI-GEN-AI", "工作完成质量(AI)", "5-16%", "L-连接协同", "简道云[任务-AI评分]")],
        "variables": [
            {"key": "purpose", "label": "目的", "required": True, "placeholder": ""},
            {"key": "draft", "label": "草稿或要点", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是商务写作助理。\n目的：{{purpose}}\n草稿：{{draft}}\n\n"
            "输出润色后的邮件；保留原意；给出更短版本。"
        ),
        "quality_notes": "保留原意不增改事实；语气得体；附更短版本。",
        "example_input": "目的：催供应商交期；草稿：你们的货晚了，快点发，我们等着用",
        "example_output": "（润色后邮件+更短版本）",
        "output_format": "email",
    },
    {
        "code": "SC-GEN-002", "title": "长文摘要与知识入库", "department": "通用", "category": "general",
        "roles": "全员", "timing": "读完长文档后", "goal": "一页摘要+可入库条目",
        "default_model": "kimi", "fallback_model": "deepseek",
        "kpi_links": [
            K("KPI-AI-DOC", "知识沉淀与主动性(AI)", "5-10%", "L-连接协同", "简道云[知识库]"),
            K("KPI-GEN-DOC", "文档记录完整度", "5-16%", "O-优化创新", "简道云[内部资料]"),
        ],
        "variables": [
            {"key": "doc_text", "label": "文档内容", "required": True, "placeholder": ""},
            {"key": "focus", "label": "关注点", "required": False, "placeholder": ""},
        ],
        "prompt_template": (
            "你是高级文秘。\n关注点：{{focus}}\n\n文档：\n{{doc_text}}\n\n"
            "输出：一页摘要；可直接进知识库的条目（标题/标签/适用范围/要点）；建议精读章节。"
        ),
        "quality_notes": "摘要控制在一页；入库条目含标题/标签/适用范围/要点；不曲解原文结论。",
        "example_input": "文档：某泵阀行业白皮书节选约3000字；关注点：市场趋势",
        "example_output": "（一页摘要+可入库条目+建议精读章节）",
        "output_format": "markdown",
    },
    {
        "code": "SC-GEN-003", "title": "PPT大纲与讲稿", "department": "通用", "category": "general",
        "roles": "全员", "timing": "汇报前", "goal": "大纲+讲稿",
        "default_model": "kimi", "fallback_model": "mimo",
        "kpi_links": [K("KPI-GEN-AI", "工作完成质量(AI)", "5-16%", "L-连接协同", "简道云[任务-AI评分]")],
        "variables": [
            {"key": "topic", "label": "主题", "required": True, "placeholder": ""},
            {"key": "audience", "label": "听众", "required": True, "placeholder": ""},
            {"key": "key_points", "label": "要点", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是汇报教练。\n主题：{{topic}}\n听众：{{audience}}\n要点：{{key_points}}\n\n"
            "输出：页级大纲+逐页讲稿要点+行动号召。"
        ),
        "quality_notes": "页级大纲逻辑清晰；每页有讲稿要点；结尾有行动号召。",
        "example_input": "主题：屏蔽泵技术优势介绍；听众：潜在客户技术负责人；要点：无泄漏/低维护/API685业绩",
        "example_output": "（页级大纲+逐页讲稿要点+行动号召）",
        "output_format": "markdown",
    },
    {
        "code": "SC-GEN-004", "title": "数据表解读", "department": "通用", "category": "general",
        "roles": "全员", "timing": "向别人解释数据前", "goal": "结论+图表建议",
        "default_model": "deepseek", "fallback_model": "mimo",
        "kpi_links": [K("KPI-GEN-AI", "工作完成质量(AI)", "5-16%", "L-连接协同", "简道云[任务-AI评分]")],
        "variables": [
            {"key": "data", "label": "数据", "required": True, "placeholder": ""},
            {"key": "question", "label": "想回答的问题", "required": True, "placeholder": ""},
        ],
        "prompt_template": (
            "你是数据分析师。\n问题：{{question}}\n数据：{{data}}\n\n"
            "输出：直接结论3条；支撑数字；异常点；图表建议；需补充数据。"
        ),
        "quality_notes": "结论直接且由数据支撑；异常点单列；不编造数据，缺数据写需补充。",
        "example_input": "数据：1–9月各月销售额表；问题：Q4能否完成年度目标？",
        "example_output": "（3条直接结论+支撑数字+异常点+图表建议+需补充数据）",
        "output_format": "markdown",
    },
]




def _usage(code: str) -> str:
    """标准开工：①资料文件夹 ②Mimo项目 ③起进入场景步骤（重新编号为④⑤⑥…）。"""
    body = WORKFLOW_MAP.get(code, ("", ""))[1] or "按场景卡推进"
    # 将体内 ①②③… 统一重编为 ④⑤⑥…
    circles = "①②③④⑤⑥⑦⑧⑨⑩"
    out = []
    seq = 2  # 开工占用①②，场景步骤从③起
    i = 0
    while i < len(body):
        ch = body[i]
        if ch in circles:
            if seq < len(circles):
                out.append(circles[seq])
                seq += 1
            i += 1
        else:
            out.append(ch)
            i += 1
    return "①资料文件夹 ②Mimo V2.6 新建项目 " + "".join(out)



def seed_scenarios(db: Session) -> int:
    created = 0
    updated = 0
    for item in SCENARIOS:
        exists = db.execute(select(Scenario).where(Scenario.code == item["code"])).scalar_one_or_none()
        payload = dict(
            code=item["code"],
            title=item["title"],
            department=item["department"],
            category=item["category"],
            roles=item["roles"],
            timing=item["timing"],
            goal=item["goal"],
            prompt_template=item["prompt_template"],
            variables=item["variables"],
            default_model=item.get("default_model", "mimo"),
            fallback_model=item.get("fallback_model", "kimi"),
            quality_notes=item.get("quality_notes", ""),
            output_format=item.get("output_format", "markdown"),
            example_input=item.get("example_input", ""),
            example_output=item.get("example_output", ""),
            kpi_links=item.get("kpi_links", []),
            security_level=item.get("security_level", "normal"),
            workflow_stage=WORKFLOW_MAP.get(item["code"], ("", ""))[0],
            usage_steps=_usage(item["code"]),
            author="V-FLO场景工作坊/KPI对齐",
            status="active",
        )
        if exists:
            for k, v in payload.items():
                if k != "code":
                    setattr(exists, k, v)
            exists.version = "2.0"
            updated += 1
        else:
            db.add(Scenario(version="2.0", **payload))
            created += 1
    db.commit()
    return created + updated
