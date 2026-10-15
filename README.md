# V-FLO 极简智能办公系统（可运行代码库）

> 场景即提示词 · 过程即资产 · 用好成熟大模型  
> 集成调度：**Mimo V2.6** / **DeepSeek Harness** / **Kimi 3**

本代码库实现设计方案中的最小可运行版本：场景广场、工作台（填空→生成→编辑→定稿）、
模型网关（推荐/切换/降级）、留痕与知产库、管理看板，以及类 DeepSeek Harness 的
「💬 智能对话」模块（上传文件解析注入上下文、多轮对话、随时换模型、历史记录留存），
并与场景广场（一键以场景提示词开聊）和工作台（对话一键送去定稿/归档）联动。
简道云模块为单向拉取体系（仿 v-crm）：独立 poller 容器周期把简道云表单（任务管理/知识库）
全量镜像到本地 `jdy_records` 表，同步日志留痕，前后端只读本地库（离线容错、零频控压力）。
工作台「📚 贡献知识库」支持**上传文件 / 在线填写 / 自动总结**三种主动贡献方式：AI 起草
问答结构（问题/回答/客户/项目/国家/备注/部门，与知识库表单字段一一对应），人工确认后
写入简道云并即时镜像回本地，可展示可搜索（部门名自动解析为 dept_no，附件上传权限未开通时
自动降级为文件名入备注）。
合规审查前移：涉外任务项目在**初步分析阶段**完成合规初筛并绑定审查单（项目卡片一键发起，
合规官终审），工作台生成只调用审查结果、不重复审查——项目会话的出口管制/敏感场景在审查
未放行时直接阻断并引导回项目；审查规则（国家名单/物项提示词/红线/红旗/十二项清单/决策文案）
与选型软件等资料全部配置化入库（`compliance_rules` 表），审查引擎实时调用，合规官/管理员
可在「出口管制 → 规则与资料资产」在线维护。

## 快速启动

```bash
cd vflo-smart-office
pip install -r requirements.txt
# 可选：复制 .env.example 为 .env 填入 API Key（不填则 MOCK 模式）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

浏览器打开 http://127.0.0.1:8000  
开发登录：填写姓名/部门/岗位即可进入（生产替换为企业微信 OAuth）。

## 目录结构

```
vflo-smart-office/
├── app/
│   ├── main.py              # 入口
│   ├── config.py            # T01 配置
│   ├── database.py          # T02 数据模型
│   ├── auth.py              # T03 鉴权
│   ├── schemas.py           # API 契约
│   ├── routers/api.py       # T05/T10 路由
│   ├── routers/chat.py      # 智能对话：文件上传/多轮对话/换模型/历史
│   ├── services/
│   │   ├── model_gateway.py # T04 三模型网关
│   │   ├── file_extract.py  # 附件文本解析（txt/md/csv/log/json/docx/xlsx/pdf）
│   │   └── prompt_builder.py# T06 提示词拼装 + diff
│   └── seed/scenarios.py    # T13 按部门场景卡（30+）
├── web/                     # T12 前端工作台
├── docs/                    # 开发任务清单与分项方案
├── tests/                   # 冒烟测试
├── requirements.txt
└── .env.example
```

## 工程门禁（对应总方案第4章）

1. 生产必须 PostgreSQL（改 `DATABASE_URL`）
2. 生产必须企业微信 OAuth（关 `ENABLE_DEV_LOGIN`）
3. 密钥进环境变量，禁止明文入库
4. API 路径统一 `/api/...`
5. 人工定稿 diff 强制落库
6. 两周真实用户演示

## 角色权限（RBAC）与登录

| 角色 | 权限 |
|------|------|
| staff 员工 | 全部业务功能（场景/工作台/对话/任务/简报/初筛提交） |
| manager 部门经理 | + 本部门推送统计（简报页签入口，强制锁定本部门） |
| compliance 合规官 | + 出口管制审查单终审（禁止自审） |
| admin 管理员 | + 全局看板 / KPI / 知产精选 / **用户管理（角色分配、账号停用）** |

- 权限点集中在 `app/auth.py: ROLE_PERMS`，路由统一 `Depends(require_perm("..."))` 校验
- 登录隔离：账号停用/改角色即时生效（token 无状态、每请求查库）；防误锁（不得自降级/自停用）
- 首个 admin 由 `DEV_ADMIN_USERS` 白名单产生；之后一律用「管理看板 → 用户管理」分配角色
- 企业微信扫码登录：`/auth/wecom/config|qr-url|callback`（state 防 CSRF，code 一次性）；
  未配置凭证或内网出网失败自动降级开发登录；上线 checklist 见 `deploy/README-部署.md` §7.1

## 验收冒烟

```bash
python -m tests.smoke          # 进程内冒烟；检测到真实模型 Key 时自动续跑 E2E（mock 自动跳过）
python -m tests.smoke --no-e2e # 只跑进程内冒烟（或 RUN_E2E=0）
python tests/test_chat.py      # 智能对话专项：附件解析（docx/xlsx/pdf/gbk）+ 上传/会话边界
python tests/test_rbac.py      # 角色权限/登录隔离/企微扫码框架（monkeypatch 企微，无需真实网络）
python tests/test_jdy_sync.py  # 简道云镜像：upsert/prune/截断保护/标签友好化/权限（monkeypatch 拉取）
python tests/test_knowledge.py # 贡献知识库：字段映射/三种方式/部门解析/附件降级/镜像可见可搜
python tests/test_compliance.py# 合规前移：规则配置化/项目初筛绑定/工作台只读结果/409阻断放行
```

# 真实链路 E2E（登录→建会话→生成→定稿→归档），需真实模型 Key
python tests/e2e_real.py --base-url http://127.0.0.1:8000  # 附着已启动服务
python tests/e2e_real.py --spawn                           # 自拉起临时实例（临时库，跑完销毁）
python tests/e2e_real.py --require-real                    # 发布门禁：目标为 mock 时退出码 2
```

mock 判定与服务端一致（`MOCK_LLM=1/true/yes/on` 强制 mock，或未配置任何模型 Key 时自动 mock）；
mock 模式下 E2E 按规则跳过、退出码仍为 0。
