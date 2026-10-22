"""Run the arq workers and the scheduler inside the API process.

For hosts that give one web service and nothing else (Render free tier). Same code paths as the separate
`app.workers.main` / `app.workers.scheduler` processes, with smaller per-queue concurrency.
"""

from __future__ import annotations

import asyncio
import contextlib

from arq.worker import Worker

from app.core.config import get_settings
from app.core.logging import get_logger
from app.workers.main import QUEUE_CONFIG, build_worker, close_worker
from app.workers.scheduler import run_loop

log = get_logger("embedded")


class EmbeddedWorkers:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._workers: list[Worker] = []
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> None:
        cap = get_settings().embedded_max_jobs
        self._workers = [build_worker(q, max_jobs_cap=cap) for q in QUEUE_CONFIG]
        self._tasks = [asyncio.create_task(w.async_run(), name=f"arq-{i}") for i, w in enumerate(self._workers)]
        self._tasks.append(asyncio.create_task(run_loop(self._stop), name="scheduler"))
        log.info("embedded_workers_started", queues=list(QUEUE_CONFIG), max_jobs=cap)

    async def stop(self) -> None:
        self._stop.set()
        for w in self._workers:
            with contextlib.suppress(Exception):
                await close_worker(w)
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
