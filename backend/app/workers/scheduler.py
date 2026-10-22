"""Scheduler: claims due checks from Postgres and enqueues them.

Correctness comes from the database, not from a single leader:
  * `FOR UPDATE SKIP LOCKED` lets any number of scheduler replicas claim disjoint batches.
  * A lease (`lease_until` + random `lease_token`) marks a claimed check; the worker must present the token.
    If a worker dies, the lease expires and the check is claimed again (at-least-once, idempotent runs).
  * Backpressure: when the checks queue is deep, the scheduler claims less.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from datetime import UTC, datetime

from prometheus_client import start_http_server
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import dispose_engine, session_scope
from app.core.logging import configure_logging, get_logger
from app.observability.metrics import QUEUE_DEPTH, SCHED_CLAIMED, SCHED_LAG
from app.observability.tracing import setup_tracing
from app.workers.queue import Q_CHECKS, close_pool, enqueue, queue_depth

log = get_logger("scheduler")

CLAIM_SQL = text(
    """
    WITH due AS (
        SELECT id FROM checks
        WHERE enabled
          AND next_run_at <= now()
          AND (lease_until IS NULL OR lease_until < now())
        ORDER BY priority DESC, next_run_at
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE checks c
       SET lease_until = now() + make_interval(secs => :lease),
           lease_token = substr(md5(random()::text || clock_timestamp()::text), 1, 16)
      FROM due
     WHERE c.id = due.id
    RETURNING c.id, c.lease_token, c.next_run_at
    """
)


async def tick() -> int:
    s = get_settings()
    depth = await queue_depth(Q_CHECKS)
    QUEUE_DEPTH.labels(queue="checks").set(depth)
    room = max(0, s.scheduler_max_queue_depth - depth)
    limit = min(s.scheduler_batch_size, room)
    if limit <= 0:
        log.warning("scheduler_backpressure", depth=depth)
        return 0
    async with session_scope() as session:
        rows = (await session.execute(CLAIM_SQL, {"limit": limit, "lease": s.scheduler_lease_seconds})).all()
    now = datetime.now(UTC)
    for check_id, token, due_at in rows:
        SCHED_LAG.observe(max(0.0, (now - due_at).total_seconds()))
        await enqueue("run_check", str(check_id), token, queue=Q_CHECKS, job_id=f"check:{check_id}:{token}")
    if rows:
        SCHED_CLAIMED.inc(len(rows))
        log.info("scheduler_claimed", count=len(rows))
    return len(rows)


async def run_loop(stop: asyncio.Event) -> None:
    s = get_settings()
    log.info("scheduler_started", tick=s.scheduler_tick_seconds)
    while not stop.is_set():
        try:
            claimed = await tick()
        except Exception:
            log.exception("scheduler_tick_failed")
            claimed = 0
        # if we filled a whole batch there is probably more due work: loop immediately
        if claimed < s.scheduler_batch_size:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=s.scheduler_tick_seconds)


async def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    setup_tracing("watchtower-scheduler")
    with contextlib.suppress(OSError):
        start_http_server(s.worker_metrics_port + 1)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, stop.set)
    await run_loop(stop)
    await close_pool()
    await dispose_engine()


def _windows_loop_policy() -> None:
    import sys

    if sys.platform == "win32":  # psycopg async needs a selector loop on Windows (dev only)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


if __name__ == "__main__":
    _windows_loop_policy()
    asyncio.run(main())
