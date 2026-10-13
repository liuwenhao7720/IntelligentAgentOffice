【只读分析报告】V-FLO 场景卡种子数据 vs 规范场景卡矩阵
（代码：app/seed/scenarios.py、app/seed/mature_rules_dept.py、app/services/mature_rules.py、app/database.py；规范：_spec_extract/01_开发方案_KPI与出口管制.txt、03_设计方案.txt、05_使用指导说明书.txt。未修改任何文件。）

========== A. 53卡矩阵覆盖情况 ==========

A1. 规范01《第一章 部门×岗位×场景×KPI矩阵（53卡）》+ §2.5 合规卡要求的 53 个编号，在 app/seed/scenarios.py 的 SCENARIOS 列表中全部存在（AST 解析实测 = 53 张卡）：
- SC-PRJ-001~007（7张，规范01 §1.1）✅ 全部存在
- SC-SAL-001~006（6张，§1.2）✅
- SC-ENG-001/002/003/011/012/013（6张，§1.3）✅（跳号与规范一致）
- SC-PMP-001/002、SC-RND-001~003、SC-PRD-001~003、SC-QA-001~003（§1.4）✅
- SC-FIN-001~003、SC-HR-001~004、SC-GM-001~003、SC-AI-001~003（§1.5）✅
- SC-GEN-001~004（§1.5 末行“通用办公四卡”）✅
- SC-EXP-001~006（§2.5，6张合规卡）✅，且 6 张均设 security_level="export_control"，名称/触发时机与 §2.5 表逐张对应
- 抽查推荐模型与规范矩阵一致：SC-PRJ-001 kimi、SC-PRJ-004 deepseek、SC-ENG-012 mimo、SC-QA-002 kimi、SC-AI-003 mimo 等均吻合

A2. SC-PRJ-101 / SC-ENG-101（规范05 §8.3 成熟规则）：
- ❌ 不在 app/seed/scenarios.py 中
- ✅ 实际位于 app/services/mature_rules.py 的 MATURE_RULES 列表（SC-PRJ-101 在 :25，SC-ENG-101 在 :75），由 seed_mature_rules()（:125）入库；文件归属偏离规范01 §3.1「seed/scenarios.py：53张卡…」的描述（成熟规则种子放在 services 而非 seed 目录）

A3. 多余（规范矩阵之外）的卡：app/seed/mature_rules_dept.py 的 DEPT_RULES 共 13 张 draft 规则，均不在规范 53+2 清单内：
SC-SAL-201、SC-SAL-202、SC-QA-201、SC-QA-202、SC-ENG-201、SC-PMP-201、SC-RND-201、SC-PRD-201、SC-FIN-201、SC-HR-201、SC-GM-201、SC-AI-201、SC-GEN-201。
（注：规范05 §8.3 第3行“其他部门同类规则…逐步固化”为其提供依据，属规范允许但未逐张定义；规范03 §6“首批30张”用 SC-SAL-01 等旧编号，已被 v2.0 矩阵取代，种子中不存在也不应存在。）

结论：规范要求的 55 个编号（53+2）在种子链路上零缺失；多出 13 张部门 draft 规则。

========== B. 已存在卡字段完整性（对照规范03 §1.3 + §1.4 + 规范01 §一） ==========

对 scenarios.py 53 张卡逐字段 AST 解析：

✅ 完整（53/53）：
- 场景编号/名称 code/title（§1.3）
- 适用岗位与触发时机 roles/timing（§1.3；亦满足规范01 §0.1“场景标注适用岗位层级”）
- 业务目标 goal、输入变量 variables（含 required 标志，支撑 §1.4②“缺关键变量禁止调用”）、prompt_template（角色先行+双花括号变量+输出格式与约束内嵌，符合 §1.4①②③④）
- 推荐模型+备选 default_model/fallback_model（§1.3）每张卡均有
- 关联KPI+简道云来源：kpi_links 53/53 非空，每条经 K() 帮助函数带齐 code/name/weight/dimension/source 五元组，source 形如“简道云[项目管理→项目计划/结项]”（满足规范01 §一“每张卡标注关联KPI与简道云数据来源”、§0.1“KPI从简道云自动提取”）
- workflow_stage/usage_steps：不在卡字典内，由 WORKFLOW_MAP（53 键全覆盖）在 seed_scenarios()（scenarios.py:1111-1112）注入，对应规范05 第九章岗位工作流矩阵

⚠️ 缺失/不足：
1. quality_notes（质量要点，§1.3）：仅 3/53 张填写——SC-PRJ-001、SC-PRJ-007、SC-AI-003；其余 50 张为空（seed :1106 默认空串）
2. example_input/example_output（示例，§1.4⑥“示例必填”）：仅 SC-PRJ-001 一张有 → 52/53 违反 §1.4⑥
3. output_format（§1.3 独立字段）：53/53 均未显式设置，仅靠 database.py:44 默认值 markdown；格式要求只写在 prompt 文本里
4. version/author（§1.3“版本与作者”）：卡字典不含；seed_scenarios() 统一硬编码 version="2.0"、author="V-FLO场景工作坊/KPI对齐"（:1113/:1120/:1123）——入库有值但无单卡粒度，无法体现 §1.3 示例“v1.2 · 张工”式单卡版本与作者
5. 连带动作（§1.3“产出后一键做什么”）：数据库模型与种子均无独立字段，仅 usage_steps 文本部分覆盖 → 字段级缺失
6. security_level：SC-EXP-001~006 显式设 export_control ✅；其余 47 张走 seed 默认 normal（:1110）——结果正确但非显式

========== C. 成熟规则 seed 与 规范05 §8.3/§8.3.1/§8.3.2 的差异 ==========

✅ 一致项：
- 状态字段：SC-PRJ-101 maturity="production"（mature_rules.py:29）、SC-ENG-101 maturity="validated"（:79），与 §8.3 表一致；database.py:60 maturity 列支持 draft/validated/production 三态，契合 §8.3.3 升级路径
- 审核放行标志：generate_with_review() 对 production 产出 review_status="awaiting_review" 并附“【审核状态】awaiting_review…未放行=不得发出”横幅（:189-195），符合 §8.3“强制 awaiting_review→经理审核→放行”与 §8.3.1“输出一律标【草稿·待项目经理审核放行】”；validated 标 draft 建议审核（:196-201），符合 §8.3 SC-ENG-101 行；API 提供 /mature-rules/review/{session_id}（routers/api.py:722）
- 红线 §8.3.1：十二条铁律逐条写入 SC-PRJ-101 prompt_template（:54-68），含图片 A/B/C 三类强制标注与“严禁伪造业绩、证书、检测报告”✅
- 红线 §8.3.2：SC-ENG-101 模板含四条红线（存工作区/禁止臆造/禁止跳项/禁止断链）、双报告、合规四态+风险四级、证据链置信度<0.70 进人工复核、TMD 位号主数据表唯一数据源、“单价×数量+费率”（:104-116）✅
- DEPT_RULES 13 张全部 maturity="draft"，符合 §8.3“其他部门同类规则 draft→validated→production”

⚠️ 差异项：
1. 放行留痕无结构化字段：apply_review()（:241-289）把审核结论仅拼接进一条 model="human-review" 的消息文本；session.progress_note 赋值因 ChatSession 无该列、hasattr 恒 False（:254）→ 审核人/意见不落结构化字段，与 §8.3 放行留痕口径及规范01 §2.1 G5“审批记录留痕”存在差距
2. 状态映射瑕疵：status_map 将 approve→approved 后立即覆写为 done（:273-280），终态只有 done/revising/rejected，库中不存在 approved 态
3. kpi_links 缺简道云来源：MATURE_RULES 与 DEPT_RULES 的 kpi_links 只有 code/name/weight/dimension 四键，无 source 键（对照 scenarios.py 的 K() 五元组）→ 违反规范01 §一“每张卡标注关联KPI与简道云数据来源”
4. SC-PRJ-101 变量 stage 的 placeholder 写 G1/G2/G3/G5/G6（:44），跳过 G4，与 §8.3“阶段(G1–G6)”不完全一致
5. 成熟规则卡均无 example_input/example_output（§1.4⑥）、无显式 output_format；seed_mature_rules 统一 version="1.0"、author="成熟规则库"（:147-148），与 scenarios 的 2.0/V-FLO场景工作坊口径不一
6. 文件归属：规范01 §3.1 称场景卡种子在 seed/scenarios.py，而 SC-PRJ-101/SC-ENG-101 实际在 services/mature_rules.py

========== D. 数据库 Scenario 模型（database.py:29-62）vs 规范要求字段 ==========

✅ 已满足：
- 规范01 §3.1“Scenario 增加 kpi_links / security_level”：:53 kpi_links(JSON)、:55 security_level 均存在，注释明示 V/F/L/O 四维（:52）与 normal/export_control/sensitive 取值（:54），对齐规范01 §0.1 KPI 四维与 §2.4 合规分级
- 规范03 §4.2 scenario 表全部 14 个要求字段（id/code/title/roles/timing/goal/prompt_template/variables/default_model/output_format/version/status/author/use_count）逐一存在
- 超规范增强：fallback_model（§1.3 备选 + §2.2 故障降级）、quality_notes、example_input/example_output（§1.4⑥）、workflow_stage/usage_steps（规范05 第九章）、maturity（规范05 §8.3.3）

⚠️ 差异/缺口：
1. §1.3“连带动作”无对应列（最接近的是 usage_steps 文本，非结构化动作）
2. 无结构化“审核放行”字段（放行状态寄生在 ChatSession.status 与消息文本，见 C-1）
3. 迁移缺口：migrate_db()（database.py:250-285）只为 task_items 补 4 列；scenarios 表的 kpi_links/security_level/workflow_stage/usage_steps/maturity 等后增列不在迁移清单，旧库 create_all 不会 ALTER → 规范01 §3.1 的“Scenario 增加列”对存量库有升级风险（新库无影响）
4. security_level 语义为出口管制标记，与规范03 §3.4 数据密级“公开/内部/秘密”是两套口径；密级落在 Asset.visibility（:115）而非 Scenario——设计可自洽但命名易混淆

========== 总结 ==========
- 矩阵覆盖：规范 55 个编号（53 卡 + 2 成熟规则）零缺失；额外 13 张规范未逐张定义的部门 draft 规则（SC-*-2xx）
- 最大共性短板：示例字段 52/53 缺失（违反规范03 §1.4⑥）、quality_notes 50/53 缺失、output_format 53/53 依赖默认值、“连带动作”无字段
- 成熟规则：内容与分级高度吻合 §8.3.x，主要差距在审核放行结构化留痕与 kpi_links 缺简道云 source
- 模型层：满足规范01 §3.1 与规范03 §4.2，缺连带动作列与 scenarios 表列迁移