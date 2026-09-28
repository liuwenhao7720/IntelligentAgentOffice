# V-FLO 极简智能办公系统（可运行代码库）

> 场景即提示词 · 过程即资产 · 用好成熟大模型  
> 集成调度：**Mimo V2.6** / **DeepSeek Harness** / **Kimi 3**

本代码库实现设计方案中的最小可运行版本：场景广场、工作台（填空→生成→编辑→定稿）、
模型网关（推荐/切换/降级）、留痕与知产库、管理看板。

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
│   ├── services/
│   │   ├── model_gateway.py # T04 三模型网关
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

## 验收冒烟

```bash
python -m tests.smoke
```
