"""Async SQLAlchemy engine/session management."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
            # Supabase's transaction pooler (pgbouncer) does not support prepared statements.
            connect_args={"statement_cache_size": 0, "server_settings": {"application_name": "watchtower"}},
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


def after_commit(session: AsyncSession, fn: Callable[[], Awaitable[object]]) -> None:
    """Run `fn` only once the surrounding unit of work has committed (e.g. enqueue a job for a new row)."""
    session.info.setdefault("after_commit", []).append(fn)


async def _run_after_commit(session: AsyncSession) -> None:
    callbacks = session.info.pop("after_commit", [])
    for fn in callbacks:
        await fn()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Unit-of-work: commits on success, rolls back on error, then runs after-commit callbacks."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            session.info.pop("after_commit", None)
            await session.rollback()
            raise
        await _run_after_commit(session)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
