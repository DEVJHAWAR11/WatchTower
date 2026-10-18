"""Job enqueueing (arq on Redis). Queues are separated so slow agent work never starves checks or notifications."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

Q_CHECKS = "wt:checks"
Q_AGENTS = "wt:agents"
Q_NOTIFY = "wt:notify"
Q_MAINT = "wt:maintenance"
ALL_QUEUES = {"checks": Q_CHECKS, "agents": Q_AGENTS, "notify": Q_NOTIFY, "maintenance": Q_MAINT}

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None


async def enqueue(func: str, *args: Any, queue: str, job_id: str | None = None,
                  defer_seconds: float | None = None, **kwargs: Any) -> bool:
    """Returns False if a job with the same id is already queued/running (arq dedup) or Redis is down."""
    try:
        pool = await get_pool()
        job = await pool.enqueue_job(
            func, *args, _queue_name=queue, _job_id=job_id,
            _defer_by=timedelta(seconds=defer_seconds) if defer_seconds else None, **kwargs,
        )
        return job is not None
    except Exception as e:  # the sweepers re-enqueue anything that was missed
        log.error("enqueue_failed", func=func, queue=queue, error=str(e))
        return False


async def queue_depth(queue: str) -> int:
    pool = await get_pool()
    return int(await pool.zcard(queue))
