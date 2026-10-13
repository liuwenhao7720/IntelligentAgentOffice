# 登录报错与多用户并发问题 · 诊断与修复报告

日期：2026-09-30 · 系统：V-FLO 极简智能办公系统（uvicorn 4 workers + PostgreSQL + nginx）

---

## 一、问题 1：用户登录报错

### 1.1 错误现象与复现记录

| # | 现象 | 复现步骤 | 实测结果（修复前） |
|---|------|----------|--------------------|
| A | 登录成功后被强制退出，提示"登录失效，请重新登录" | ①任意用户登录成功 ②携带令牌连续请求 `GET /api/auth/me` 20 次 | 约 25% 请求返回 **401 {"detail":"令牌无效或已过期"}**，前端 `api()` 收到 401 即 logout |
| B | 登录后变成"别人"（更严重的串号） | 用户"复现张三"登录得令牌 `dev-token-12`，再请求 `/auth/me` | 返回 **200 但身份是"张工"(id=4)** —— 同一令牌在不同 worker 上解析为不同用户 |
| C | 登录接口直接报 500 | 同一新用户并发提交 8 次登录请求 | **4/8 返回 500 Internal Server Error**（`users.wecom_userid` 唯一约束冲突） |
| D | 任意访客可拿管理员 | 登录请求体传 `role:"admin"` | 服务端照单全收，返回 `role=admin`（越权） |

### 1.2 根本原因

1. **令牌存于进程内存**（`app/auth.py` 旧实现 `_DEV_TOKENS` 字典 + 顺序计数器 `_TOKEN_SEQ`）。
   生产 `docker-compose.yml` 以 `uvicorn --workers 4` 运行，4 个进程各自独立：
   - 登录请求落在 worker A，令牌只写进 A 的内存；后续请求被分发到 B/C/D → 401（现象 A）；
   - 每个 worker 计数器都从 1 开始，`dev-token-12` 在 A 是张三、在 B 是张工 → **跨用户串号、数据越界**（现象 B）；
   - 服务重启所有令牌作废，全员被踢。
2. **登录"先查后插"竞态**：并发首次登录同一用户时，多个请求同时查不到记录、同时 INSERT，
   触发唯一约束 `IntegrityError` 未捕获 → 500（现象 C）。
3. **角色字段信任客户端**：`DevLoginIn.role` 直接入库，无白名单校验（现象 D）。
4. **输入验证薄弱**：姓名/部门/岗位无长度限制，role 无取值约束。

### 1.3 修复内容

| 文件 | 修改 |
|------|------|
| `app/auth.py` | 重写令牌机制：**HMAC-SHA256 无状态签名令牌** `vflo1.<payload>.<signature>`，payload 含 uid/iat/exp/nonce；任意 worker 可独立验签（常数时间比较）；自带过期（默认 7 天）；含随机 nonce，令牌不可预测、不可伪造、多次登录互不冲突；重启不失效 |
| `app/routers/api.py` | `dev_login`：捕获 `IntegrityError` → 回滚重查（修复并发 500）；role 仅对 `DEV_ADMIN_USERS` 白名单生效，其余强制 staff；老用户 role 以数据库为准（登录不升降权）；输入规范化 |
| `app/schemas.py` | `DevLoginIn` 增加长度上限与 role 取值白名单（`staff|admin`），非法输入 422 |
| `app/config.py` | 新增 `TOKEN_TTL_HOURS`（默认 168）、`DEV_ADMIN_USERS`（管理员白名单） |
| `web/app.js` | 登录防重复提交（按钮置灰"登录中…"）；登录框回车提交；失败提示带"登录失败："前缀 |

## 二、问题 2：多用户并发访问

### 2.1 架构评估结论

- **会话隔离**：业务数据查询（会话/任务/项目/合规单）原本均按 `user_id` 过滤，方向正确；
  但令牌串号（1.1-B）使隔离形同虚设 —— 已随令牌机制修复根除。
- **启动竞态（新发现）**：4 个 worker 并发执行 `create_all` + 种子数据插入，新库上必现
  `table users already exists` / `UNIQUE constraint failed: scenarios.code`，
  子进程启动失败导致**父进程连带全部停止**（服务间歇性整体不可用）。已在 `app/main.py`
  增加重试+回滚幂等处理（修复前压测 2/5 轮触发，修复后 6/6 轮全部通过）。
- 数据层每请求独立 Session + 连接池（pre_ping/recycle），无共享可变全局状态，满足并发要求。

### 2.2 并发能力验证（多 worker 真实实例，4 workers）

`tests/test_auth_concurrency.py` 共 30 项断言，独立实例 6/6 轮全过、线上实例 29 过
（唯一"失败"项为 T6.3：线上白名单为空属预期安全配置）：

- T1 16 路并发同名首登 → 全 200、同 user_id
- T2 20 用户并发登录 → 全 200、id 唯一
- T3 100 次混合并发 `/auth/me` → 0 个 401、0 串号
- T4/T5 伪造、篡改、过期、缺失令牌 → 全 401
- T6 越权申请 admin → staff；白名单 → admin；老用户不升权
- T7 跨用户读/写会话与任务项目 → 全 404，列表零泄露
- T8 空/超长姓名、非法 role、坏 JSON → 全 422
- T9 同账号多端令牌并行有效
- T10 20 用户并发读写压测 → 无错误、无串数据

## 三、回归与部署

- `tests/smoke.py` 冒烟（登录→场景→生成→定稿→知产→统计→出口管制→任务项目）全部通过；
  新增断言：白名单用户得 admin、非白名单申请 admin 被钳制且访问管理接口 403。
- 已部署：`vflo-app` 重启加载新代码，4 worker 全部正常启动；nginx(8008) 与 app(8000) 均验证通过。
- 生产库已清理本次诊断产生的 62 个测试用户及其数据；原有 6 个真实用户数据完好。
- **注意**：旧 `dev-token-N` 令牌已失效，用户下次操作会被引导重新登录一次（前端自动处理）。
- **运维建议**：在 `.env` 的 `DEV_ADMIN_USERS` 填入真实管理员姓名（如 `DEV_ADMIN_USERS=张三,李四`），
  否则无任何人可通过登录页获得 admin（数据库中已有 admin 不受影响）。

## 五、「今日工作安排」优化与补充（2026-09-30）

**核验**：_patch_today*.py 描述的改造已全部落盘且与既有登录/并发修复正确合并；
tests/test_today.py（10 项 + 迁移项）、tests/smoke.py、tests/test_auth_concurrency.py（30 项）全绿。

**附件核对**：
- 《简道云各模块详细接口字段信息汇总表.xlsx》：`JDY_FIELD_MAP` 的 20 个 widget ID 与真实
  「任务管理」表单（entry_id=65f2a8677a89ace938810a28，与 .env 一致）逐字段核对，**完全吻合，无需调整**。
- 《简道云开放平台API接口清单.xlsx》：v5 数据写接口与 `app/services/jdy.py` 现有调用一致。
- 《企业微信.docx》：智能机器人 Bot ID/Secret 已配置于 .env（WECOM_BOT_ID 一致）。

**本轮补充**：
1. **审计补齐**（方案遗留事项 4）：briefing.evening / weekly_plan / weekly_summary /
   project_closure / push_jdy、 mature.generate / mature.review 全部落审计（test_today 第 10 项覆盖）。
2. **语音录入**（方案遗留事项 1）：今日录入框新增 🎤 按钮，浏览器 SpeechRecognition 中文识别，
   不支持时自动隐藏（渐进增强，零后端改动）。
3. **并发迁移竞态修复**（部署时新发现）：4 worker 并发 `ALTER TABLE ADD COLUMN` 在 PG 抛
   `DuplicateColumn(ProgrammingError)` 曾致 worker 启动失败；migrate_db 现已容忍「列已存在」，
   启动钩子重试范围扩至 SQLAlchemyError。重新部署后 4 worker 启动零报错。

## 四、后续配置变更（2026-09-30）

- 应要求设置 `DEV_ADMIN_USERS=admin`：姓名 `admin` 登录即获管理员（白名单对老账号补授 admin，
  名单外申请 admin 仍一律钳制为 staff）。
- 已验证：admin（信息部/总经办）登录 → admin，管理看板 200；普通用户申请 admin → staff 403。
- 注意：`docker restart` 不会重读 `.env`，环境变量变更须用 `docker compose up -d app`；
  代码变更须 `docker compose build app && docker compose up -d app`（镜像已重建，修复全部固化进镜像）。
