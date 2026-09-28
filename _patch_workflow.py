# -*- coding: utf-8 -*-
"""给场景卡补 workflow 字段（T13 升级：岗位 × 工作流节点）。"""
from pathlib import Path

ROOT = Path(r"C:\Users\wognd\Desktop\小米文件夹\V-FLO集团智能办公系统开发方案\vflo-smart-office")

# code -> (workflow_stage, usage_steps)
MAP = {
    "SC-PRJ-001": ("项目执行-周报", "①收集本周事实 ②填空 ③生成 ④改稿 ⑤发客户/上级并归档"),
    "SC-PRJ-002": ("售前-询价投标", "①读标书 ②填范围与国别 ③生成方案骨架 ④补澄清问题 ⑤交经理审核"),
    "SC-PRJ-003": ("售前-澄清闭环", "①粘贴客户问题 ②写我方要点 ③生成回复 ④经理确认 ⑤发出并归档"),
    "SC-PRJ-004": ("执行-合同交接", "①摘关键条款 ②生成交接包 ③发各接口部门 ④建简道云项目任务"),
    "SC-PRJ-005": ("执行-风险管控", "①填进度事实 ②生成风险表 ③会前发经理"),
    "SC-PRJ-006": ("执行-俄文文件", "①粘贴俄文 ②生成摘要与冲突点 ③内部交底"),
    "SC-PRJ-007": ("收尾-知识沉淀", "①写经过与经验 ②生成条目 ③上传简道云知识库"),
    "SC-SAL-001": ("销售-周经营", "①填数据要点 ②生成周报 ③发经理会"),
    "SC-SAL-002": ("销售-客户沟通", "①选语言 ②写目的要点 ③生成邮件 ④发出"),
    "SC-SAL-003": ("销售-合同审核", "①粘贴条款 ②生成风险表 ③经理/法务复核"),
    "SC-SAL-004": ("跟单-六块管控", "①填六块现状 ②生成看板摘要 ③项目会使用"),
    "SC-SAL-005": ("采购-比价催交", "①选用途 ②填信息 ③生成比价/催交函"),
    "SC-SAL-006": ("市场-洞察沉淀", "①填活动信息 ②生成洞察 ③录简道云市场活动"),
    "SC-ENG-001": ("售前-选型", "①填工况 ②填候选 ③生成对比 ④交报价"),
    "SC-ENG-002": ("售前-成本", "①填BOM要点 ②生成成本骨架 ③定价评审"),
    "SC-ENG-003": ("售前-需求解析", "①粘贴规格书 ②生成澄清清单 ③发客户"),
    "SC-ENG-011": ("交付-文件计划", "①填订单与文件要求 ②生成清单 ③建任务跟踪"),
    "SC-ENG-012": ("交付-批复处理", "①粘贴批复 ②生成处理单 ③3日内回复"),
    "SC-ENG-013": ("交付-三维修改", "①填修改与零件 ②生成核对清单 ③改模"),
    "SC-PMP-001": ("研发-选型设计", "①填工况 ②生成选型与数据表 ③评审"),
    "SC-PMP-002": ("研发-计算校核", "①填设计对象 ②生成计算书结构 ③评审"),
    "SC-RND-001": ("研发-立项计划", "①填项目目标 ②生成计划 ③录入简道云五要素"),
    "SC-RND-002": ("质量-NCR处置", "①填NCR事实 ②生成处置建议 ③验证关闭"),
    "SC-RND-003": ("研发-BOM变更", "①填变更明细 ②生成变更单 ③通知采购/生产"),
    "SC-PRD-001": ("生产-日报交接", "①填完成与异常 ②生成日报 ③传简道云"),
    "SC-PRD-002": ("生产-设备保障", "①填设备现象 ②生成报修单 ③报修"),
    "SC-PRD-003": ("生产-工艺培训", "①填工序 ②生成要点卡 ③班组学习"),
    "SC-QA-001": ("质量-问题闭环", "①填问题 ②生成8D ③内部评审后回复客户"),
    "SC-QA-002": ("质量-月度改进", "①填质量数据 ②生成月报 ③质量会"),
    "SC-QA-003": ("质量-检验记录", "①填检验结果 ②生成规范记录 ③归档"),
    "SC-FIN-001": ("财务-结账", "①填进度 ②生成检查单 ③按单结账"),
    "SC-FIN-002": ("财务-税务", "①填税种公司 ②生成提醒清单 ③申报"),
    "SC-FIN-003": ("财务-报销", "①填单据 ②生成初审要点 ③入账"),
    "SC-HR-001": ("人力-招聘", "①填岗位要求 ②生成JD面试题 ③发布"),
    "SC-HR-002": ("人力-培训", "①填培训信息 ②生成纪要学时 ③录简道云"),
    "SC-HR-003": ("人力-绩效", "①填事实 ②生成面谈提纲 ③面谈"),
    "SC-HR-004": ("人力-行政", "①填要点 ②生成通知 ③发布"),
    "SC-GM-001": ("经营-月度分析", "①填数据议题 ②生成一页纸 ③经营会"),
    "SC-GM-002": ("经营-战略执行", "①填战略要点 ②生成任务分解 ③录简道云"),
    "SC-GM-003": ("经营-决策评审", "①填事项方案 ②生成评审材料 ③决策会"),
    "SC-AI-001": ("AI-需求立项", "①填需求 ②生成任务书 ③录简道云"),
    "SC-AI-002": ("AI-质量评审", "①填变更摘要 ②生成审查意见 ③合并"),
    "SC-AI-003": ("日常-任务管理", "①粘贴口语任务 ②润色 ③粘贴进简道云"),
    "SC-EXP-001": ("合规-出口初筛", "①填客户国别用途产品 ②生成审查单 ③合规官审核"),
    "SC-EXP-002": ("合规-EUC", "①填主体物项用途 ②生成EUC ③合规官审定签署"),
    "SC-EXP-003": ("合规-条款审查", "①粘贴条款 ②生成覆盖检查 ③补条款"),
    "SC-EXP-004": ("合规-技术外发", "①填资料接收方 ②生成边界确认 ③获批后再发"),
    "SC-EXP-005": ("合规-红旗升级", "①填异常事实 ②生成报告 ③立即升级"),
    "SC-EXP-006": ("合规-培训", "①填对象 ②生成培训测验 ③组织培训"),
    "SC-GEN-001": ("日常-邮件", "①填目的草稿 ②润色 ③发送"),
    "SC-GEN-002": ("日常-学习沉淀", "①粘贴文档 ②生成摘要条目 ③入知识库"),
    "SC-GEN-003": ("日常-汇报", "①填主题要点 ②生成大纲讲稿 ③汇报"),
    "SC-GEN-004": ("日常-数据分析", "①填数据问题 ②生成结论 ③展示"),
}

# 1) database: add columns if missing via source edit
db = ROOT / "app" / "database.py"
t = db.read_text(encoding="utf-8")
if "workflow_stage" not in t:
    t = t.replace(
        "    # normal / export_control / sensitive（出口管制场景强制合规审查）\n"
        "    security_level = Column(String(16), default=\"normal\")",
        "    # normal / export_control / sensitive（出口管制场景强制合规审查）\n"
        "    security_level = Column(String(16), default=\"normal\")\n"
        "    # 工作流节点与使用步骤（T13 岗位工作流矩阵）\n"
        "    workflow_stage = Column(String(64), default=\"\")\n"
        "    usage_steps = Column(String(256), default=\"\")",
    )
    db.write_text(t, encoding="utf-8")
    print("database.py: added workflow_stage/usage_steps")
else:
    print("database.py: already has workflow_stage")

# 2) seed: inject workflow into payload
seed = ROOT / "app" / "seed" / "scenarios.py"
s = seed.read_text(encoding="utf-8")
if "workflow_stage" not in s:
    s = s.replace(
        'from ..database import Scenario',
        'from ..database import Scenario\n\n'
        '# code -> (workflow_stage, usage_steps)\n'
        'WORKFLOW_MAP = ' + repr(MAP),
    )
    s = s.replace(
        '            security_level=item.get("security_level", "normal"),',
        '            security_level=item.get("security_level", "normal"),\n'
        '            workflow_stage=WORKFLOW_MAP.get(item["code"], ("", ""))[0],\n'
        '            usage_steps=WORKFLOW_MAP.get(item["code"], ("", ""))[1],',
    )
    seed.write_text(s, encoding="utf-8")
    print("scenarios.py: workflow injected")
else:
    print("scenarios.py: already has workflow")

# 3) schemas
sch = ROOT / "app" / "schemas.py"
st = sch.read_text(encoding="utf-8")
if "workflow_stage" not in st:
    st = st.replace(
        '    kpi_links: list = []\n    security_level: str = "normal"',
        '    kpi_links: list = []\n    security_level: str = "normal"\n'
        '    workflow_stage: str = ""\n    usage_steps: str = ""',
    )
    sch.write_text(st, encoding="utf-8")
    print("schemas.py: workflow fields")

print("done")
