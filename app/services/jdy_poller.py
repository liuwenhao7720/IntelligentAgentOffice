# -*- coding: utf-8 -*-
"""简道云拉取轮询（独立进程，仿 v-crm jdy-poller 容器模式）。

运行：python -m app.services.jdy_poller
- 与 web 服务（uvicorn 多 worker）分离，避免多进程重复拉取；compose 单副本部署
- 周期由 JDY_SYNC_INTERVAL_SECONDS（默认 3600s）控制；JDY_AUTO_SYNC_ENABLED=0 关闭
- 未配置凭证（mock）时空转待命，配置生效后自动开始同步
- 每轮独立 DB session、异常隔离，单轮失败不影响后续轮次
"""
from __future__ import annotations

import logging
import time

from ..config import get_settings
from ..database import SessionLocal, init_db, migrate_db
from .jdy import jdy
from .jdy_sync import run_full_sync

logger = logging.getLogger("vflo.jdy_poller")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    interval = max(60, s.jdy_sync_interval_seconds)
    init_db()
    migrate_db()
    logger.info("jdy-poller started: enabled=%s interval=%ss mock=%s",
                s.jdy_auto_sync_enabled, interval, jdy.mock)
    while True:
        if s.jdy_auto_sync_enabled and not jdy.mock:
            db = SessionLocal()
            try:
                result = run_full_sync(db)
                summary = {k: (r.get("status"), r.get("items", 0))
                           for k, r in result["entries"].items()}
                logger.info("jdy sync done: ok=%s %s", result["ok"], summary)
            except Exception:  # noqa: BLE001 — 循环常驻，单轮失败不退出
                logger.exception("jdy sync iteration failed")
            finally:
                db.close()
        else:
            logger.debug("jdy sync idle: disabled=%s mock=%s",
                         not s.jdy_auto_sync_enabled, jdy.mock)
        # 容器 stop 的 SIGTERM 会直接终止 sleep，无需自管 stop_event
        time.sleep(interval)


if __name__ == "__main__":
    main()
