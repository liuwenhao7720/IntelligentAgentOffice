# -*- coding: utf-8 -*-
"""V-FLO 极简智能办公系统 · 应用入口。
启动：uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import time
from pathlib import Path

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .database import SessionLocal, init_db, migrate_db
from .routers.api import router as api_router
from .routers.chat import router as chat_router
from .routers.compliance import router as compliance_router
from .routers.jdy_data import router as jdy_data_router
from .routers.knowledge import router as knowledge_router
from .routers.wecom_auth import router as wecom_auth_router
from .seed.scenarios import seed_scenarios
from .services.compliance_rules import seed_compliance_rules
from .services.mature_rules import seed_mature_rules

# 门禁8（附件4）：异常必须处理并提示；日志不输出敏感信息（只记路径/状态码，不记 body）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("vflo")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title=get_settings().app_name, version="1.1.0")
# 门禁4（附件4）：API 统一前缀 /api/v1；保留 /api 兼容别名（用户确认的迁移方式）
app.include_router(api_router, prefix="/api/v1")
app.include_router(api_router, prefix="/api", include_in_schema=False)
# 智能对话模块（类 DeepSeek Harness）：同一双前缀约定
app.include_router(chat_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api", include_in_schema=False)
# 企业微信扫码登录
app.include_router(wecom_auth_router, prefix="/api/v1")
app.include_router(wecom_auth_router, prefix="/api", include_in_schema=False)
# 简道云本地镜像读取（单向拉取的读侧）
app.include_router(jdy_data_router, prefix="/api/v1")
app.include_router(jdy_data_router, prefix="/api", include_in_schema=False)
# 主动贡献知识库（写侧：上传文件/在线填写/自动总结 → 简道云知识库表单）
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api", include_in_schema=False)
# 合规审查：规则/资料资产 + 项目初筛（审查前移）+ 项目合规状态（工作台只读结果）
app.include_router(compliance_router, prefix="/api/v1")
app.include_router(compliance_router, prefix="/api", include_in_schema=False)

# CORS 白名单（附件4 技术基线·安全；默认空=仅同源）
_cors = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


def _error_body(code: int, message: str) -> dict:
    return {"code": code, "message": message, "data": None}


@app.exception_handler(StarletteHTTPException)
async def http_exc_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, (str, dict)) else str(exc.detail)
    if isinstance(detail, dict):  # 422 缺变量等结构化错误：保留 detail 负载
        return JSONResponse(status_code=exc.status_code,
                            content={"code": exc.status_code, **detail, "data": None})
    if exc.status_code >= 500:
        logger.error("HTTP %s %s -> %s", request.method, request.url.path, exc.status_code)
    return JSONResponse(status_code=exc.status_code,
                        content=_error_body(exc.status_code, str(detail)))


@app.exception_handler(RequestValidationError)
async def validation_exc_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "code": 422, "message": "请求参数校验失败", "data": None,
        "errors": [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg", "")}
                   for e in exc.errors()[:10]],
    })


@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger.exception("unhandled %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500,
                        content=_error_body(500, "服务器内部错误，请稍后重试"))


@app.on_event("startup")
def on_startup() -> None:
    """多 worker 并发启动安全：建表/种子均允许并发重复执行（幂等+重试）。

    uvicorn --workers N 时每个进程都会执行本钩子；旧实现直接 create_all +
    种子插入，并发下会报 table exists / UNIQUE 冲突导致 worker 启动失败、
    父进程连带全部停止（表现为服务间歇性不可用）。
    """
    from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

    last_err = None
    for attempt in range(5):
        try:
            init_db()
            migrate_db()
            break
        except SQLAlchemyError as e:  # 并发建表/迁移：table exists / duplicate column / locked
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    else:
        raise last_err  # type: ignore[misc]

    db = SessionLocal()
    try:
        for attempt in range(5):
            try:
                created = seed_scenarios(db)
                if created:
                    print(f"[seed] 已初始化场景卡 {created} 张")
                n_rules = seed_mature_rules(db)
                if n_rules:
                    print(f"[seed] 成熟规则 +{n_rules}")
                n_cr = seed_compliance_rules(db)
                if n_cr:
                    print(f"[seed] 合规规则/资料资产 +{n_cr}")
                break
            except (IntegrityError, OperationalError) as e:
                # 其他 worker 已并发写入种子：回滚后重查（重复执行是幂等的）
                db.rollback()
                if attempt == 4:
                    raise
                time.sleep(0.5 * (attempt + 1))
    finally:
        db.close()


@app.get("/api/health")
@app.get("/api/v1/health")
def health():
    from .database import ping_db
    s = get_settings()
    db_ok = ping_db()
    return {
        "ok": db_ok,
        "app": s.app_name,
        "db": "up" if db_ok else "down",
        "database": "sqlite" if s.database_url.startswith("sqlite") else "postgresql",
        "mock_llm": s.mock_llm or not s.any_model_key(),
    }


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(WEB_DIR / "index.html"))
