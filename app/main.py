# -*- coding: utf-8 -*-
"""V-FLO 极简智能办公系统 · 应用入口。
启动：uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import SessionLocal, init_db
from .routers.api import router as api_router
from .seed.scenarios import seed_scenarios
from .services.mature_rules import seed_mature_rules

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title=get_settings().app_name, version="1.0.0")
app.include_router(api_router, prefix="/api")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        created = seed_scenarios(db)
        if created:
            print(f"[seed] 已初始化场景卡 {created} 张")
        n_rules = seed_mature_rules(db)
        if n_rules:
            print(f"[seed] 成熟规则 +{n_rules}")
    finally:
        db.close()


@app.get("/api/health")
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
