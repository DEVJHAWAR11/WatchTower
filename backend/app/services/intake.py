"""Intake sessions: start, resume (answers / URL / confirmation), and the worker job that drives the graph."""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.intake import build_intake_graph, extract_urls, recent_similar_session
from app.core.config import get_settings
from app.core.db import after_commit, session_scope
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.redis import RedisLock
from app.models import IntakeSession, Profile
from app.services.plans import consume, effective_plan_id, get_plan
from app.workers.queue import Q_AGENTS, enqueue

log = get_logger(__name__)

RESUMABLE = {"awaiting_user", "proposed"}
_saver: Any = None
_pool: Any = None
_graph: Any = None


async def get_intake_graph() -> Any:
    """LangGraph with a Postgres checkpointer (lazy, one per process)."""
    global _saver, _pool, _graph
    if _graph is None:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        _pool = AsyncConnectionPool(
            conninfo=get_settings().sync_database_url, max_size=10, open=False,
            kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        )
        await _pool.open()
        _saver = AsyncPostgresSaver(_pool)
        await _saver.setup()
        _graph = build_intake_graph(_saver)
    return _graph


async def close_intake_graph() -> None:
    global _saver, _pool, _graph
    if _pool is not None:
        await _pool.close()
    _saver = _pool = _graph = None


def clean_query(q: str) -> str:
    q = " ".join((q or "").split())
    if len(q) > 1000:
        raise ValidationFailed("Please keep the request under 1000 characters.")
    return q


async def start_intake(session: AsyncSession, user: Profile, query: str, *, origin: str = "api") -> uuid.UUID:
    q = clean_query(query)
    if not q:
        raise ValidationFailed("Describe what you want to watch.")
    dup = await recent_similar_session(user.id, q)
    if dup:
        return dup
    plan = await get_plan(session, effective_plan_id(user))
    await consume(session, user.id, "intake", "day", plan.limit("intake_per_day"),
                  message="You've reached today's limit for creating watches with the assistant.")
    row = IntakeSession(user_id=user.id, query=q, status="queued", stage="queued",
                        view={"message": "Queued…", "origin": origin})
    session.add(row)
    await session.flush()
    sid = row.id
    after_commit(session, lambda: enqueue("intake_step", str(sid), None, queue=Q_AGENTS, job_id=f"intake:{sid}:start"))
    return sid


async def resume_intake(session: AsyncSession, user: Profile, session_id: uuid.UUID, payload: dict[str, Any]) -> IntakeSession:
    row = await session.get(IntakeSession, session_id, with_for_update=True)
    if row is None or row.user_id != user.id:
        raise NotFound("Intake session not found")
    if row.status not in RESUMABLE:
        raise Conflict(f"This session is {row.status}; nothing to answer right now.")
    if row.status == "proposed" and "confirm" not in payload:
        raise ValidationFailed("Send confirm=true/false (with optional edits) for a proposal.")
    if row.status == "awaiting_user" and "answers" not in payload:
        raise ValidationFailed("Send answers for the questions.")
    row.status = "running"
    seq = int(row.rounds or 0)
    await session.flush()
    job_id = f"intake:{session_id}:{uuid.uuid4().hex[:8]}:{seq}"
    after_commit(session, lambda: enqueue("intake_step", str(session_id), payload, queue=Q_AGENTS, job_id=job_id))
    return row


async def intake_step(ctx: dict[str, Any] | None, session_id: str, resume: dict[str, Any] | None) -> dict[str, Any]:
    sid = uuid.UUID(session_id)
    lock = RedisLock(f"lock:intake:{sid}", ttl_ms=300_000)
    if not await lock.acquire():
        await enqueue("intake_step", session_id, resume, queue=Q_AGENTS, defer_seconds=3,
                      job_id=f"intake:{sid}:retry:{uuid.uuid4().hex[:6]}")
        return {"status": "locked"}
    try:
        async with session_scope() as s:
            row = await s.get(IntakeSession, sid)
            if row is None:
                return {"status": "missing"}
            prof = await s.get(Profile, row.user_id)
            if prof is None or prof.status != "active":
                row.status = "failed"
                return {"status": "inactive_user"}
            plan = await get_plan(s, effective_plan_id(prof))
            init = {
                "session_id": str(sid), "user_id": str(prof.id), "plan_id": plan.id,
                "token_limit": plan.limit("llm_tokens_per_day"), "max_sources": plan.limit("max_sources_per_watch"),
                "min_interval": plan.limit("min_interval_seconds"), "query": row.query,
                "urls": extract_urls(row.query), "answers": [], "rounds": 0, "url_asks": 0,
            }
            if resume is None and row.status != "queued":
                return {"status": row.status}
        graph = await get_intake_graph()
        config = {"configurable": {"thread_id": str(sid)}, "recursion_limit": 40}
        try:
            if resume is None:
                out = await graph.ainvoke(init, config)
            else:
                out = await graph.ainvoke(Command(resume=resume), config)
        except Exception as e:
            log.exception("intake_crashed", session_id=session_id)
            async with session_scope() as s:
                row = await s.get(IntakeSession, sid)
                if row is not None:
                    row.status = "failed"
                    row.view = {"message": "Something went wrong while setting up the watch. Please try again.",
                                "reason_code": type(e).__name__}
            return {"status": "failed"}
        return {"status": (out or {}).get("status", "unknown")}
    finally:
        await lock.release()


async def get_session(session: AsyncSession, user: Profile, session_id: uuid.UUID) -> IntakeSession:
    row = await session.get(IntakeSession, session_id)
    if row is None or row.user_id != user.id:
        raise NotFound("Intake session not found")
    return row


async def cancel_session(session: AsyncSession, user: Profile, session_id: uuid.UUID) -> IntakeSession:
    row = await get_session(session, user, session_id)
    if row.status in ("created", "refused", "rejected", "failed", "cancelled", "expired"):
        return row
    row.status = "cancelled"
    row.view = {"message": "Cancelled."}
    return row
