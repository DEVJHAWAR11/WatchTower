"""Worker entrypoint: `python -m app.workers.main --queues checks,agents,notify,maintenance`.

One arq Worker per queue, all in one process (or split across processes/containers by passing fewer queues).
Concurrency is tuned per queue: checks are I/O bound and plentiful; agent work is LLM-bound; notify is fast.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from typing import Any

from arq import cron
from arq.worker import Worker
from prometheus_client import start_http_server

from app.agents.act import act_on_alert
from app.agents.refine import refine_watch
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis
from app.fetch.client import close_http_client
from app.fetch.render import close_renderer
from app.notify.dispatch import fanout_alert, release_held, run_digests, send_delivery, send_due_reminders
from app.observability.tracing import setup_tracing
from app.services.community import moderate_watch, recompute_trending
from app.services.intake import close_intake_graph, intake_step
from app.workers.checks import run_check
from app.workers.maintenance import expire_intake, flush_llm_stats, queue_metrics, retention, sweep_stuck
from app.workers.queue import Q_AGENTS, Q_CHECKS, Q_MAINT, Q_NOTIFY, close_pool, redis_settings

log = get_logger("worker")

QUEUE_CONFIG: dict[str, dict[str, Any]] = {
    "checks": {"queue": Q_CHECKS, "functions": [run_check], "max_jobs": 50, "job_timeout": 300},
    "agents": {"queue": Q_AGENTS, "functions": [act_on_alert, intake_step, refine_watch, moderate_watch],
               "max_jobs": 16, "job_timeout": 600},
    "notify": {"queue": Q_NOTIFY, "functions": [fanout_alert, send_delivery], "max_jobs": 100, "job_timeout": 120},
    "maintenance": {
        "queue": Q_MAINT, "functions": [], "max_jobs": 4, "job_timeout": 1800,
        "cron_jobs": [
            cron(release_held, second=5, run_at_startup=False),
            cron(send_due_reminders, second=15),
            cron(run_digests, minute=set(range(0, 60, 5)), second=25),
            cron(sweep_stuck, minute=set(range(0, 60, 2)), second=35),
            cron(flush_llm_stats, second=45),
            cron(queue_metrics, second={0, 30}),
            cron(recompute_trending, minute=7, second=0),
            cron(expire_intake, minute=17, second=0),
            cron(retention, hour=21, minute=30, second=0),  # 03:00 IST
        ],
    },
}


async def _startup(ctx: dict[str, Any]) -> None:
    log.info("worker_started")


async def _shutdown(ctx: dict[str, Any]) -> None:
    await close_http_client()
    await close_renderer()
    await close_intake_graph()


def build_worker(name: str) -> Worker:
    cfg = QUEUE_CONFIG[name]
    return Worker(
        functions=cfg["functions"], queue_name=cfg["queue"], redis_settings=redis_settings(),
        max_jobs=cfg["max_jobs"], job_timeout=cfg["job_timeout"], keep_result=600, max_tries=3,
        cron_jobs=cfg.get("cron_jobs"), on_startup=_startup, on_shutdown=_shutdown, handle_signals=False,
        health_check_interval=30,
    )


async def close_worker(w: Worker) -> None:
    try:
        await w.close()
    except AttributeError as e:  # arq signals SIGUSR1 on close; Windows has no SIGUSR1 (local dev only)
        if "SIGUSR1" not in str(e):
            raise
        await w.pool.aclose() if w.pool is not None else None


async def run(queues: list[str]) -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    setup_tracing("watchtower-worker")
    with contextlib.suppress(OSError):
        start_http_server(s.worker_metrics_port)
    workers = [build_worker(q) for q in queues]
    log.info("workers_starting", queues=queues)
    try:
        await asyncio.gather(*(w.async_run() for w in workers))
    finally:
        for w in workers:
            await close_worker(w)
        await close_pool()
        await close_redis()
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queues", default="checks,agents,notify,maintenance")
    args = parser.parse_args()
    queues = [q.strip() for q in args.queues.split(",") if q.strip() in QUEUE_CONFIG]
    asyncio.run(run(queues))


def _windows_loop_policy() -> None:
    import sys

    if sys.platform == "win32":  # psycopg async needs a selector loop on Windows (dev only)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


if __name__ == "__main__":
    _windows_loop_policy()
    main()
