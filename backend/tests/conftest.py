"""Test harness.

Uses real Postgres + Redis (docker compose services by default; override with TEST_DATABASE_URL / TEST_REDIS_URL).
External services are replaced by: a local fixture web server (reached through a fake DNS resolver so the SSRF
guard stays fully active), a scriptable fake LLM, and respx for third-party HTTP APIs.
"""

from __future__ import annotations

import os

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:15432/watchtower_test")
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
os.environ.update({
    "WT_ENV": "test",
    "WT_DATABASE_URL": TEST_DB,
    "WT_REDIS_URL": TEST_REDIS,
    "WT_LOG_JSON": "false",
    "WT_LOG_LEVEL": "WARNING",
    "WT_TEST_PRIVATE_HOSTS": "site.test,shop.test,jobs.test,gov.test,news.test,evil.test,blocked.test,load.test",
    "WT_SUPABASE_URL": "https://proj.supabase.co",
    "WT_SUPABASE_ANON_KEY": "anon-key",
    "WT_SUPABASE_SERVICE_ROLE_KEY": "service-key",
    "WT_FETCH_DEFAULT_DOMAIN_INTERVAL_SECONDS": "0.2",
    "WT_TELEGRAM_BOT_TOKEN": "123:abc",
    "WT_TELEGRAM_WEBHOOK_SECRET": "tg-secret",
    "WT_RESEND_WEBHOOK_SECRET": "whsec_" + "dGVzdHNlY3JldHRlc3RzZWNyZXR0ZXN0c2VjcmV0MTI=",
    "WT_AUTH_HOOK_SECRET": "v1,whsec_dGVzdHNlY3JldHRlc3RzZWNyZXR0ZXN0c2VjcmV0MTI=",
    "WT_EMAIL_PROVIDER": "console",
})
# Real keys (for `pytest -m live`) win over placeholders.
for _k, _v in {"WT_GROQ_API_KEY": "test-groq", "WT_TAVILY_API_KEY": "test-tavily", "WT_BRAVE_API_KEY": "test-brave"}.items():
    os.environ.setdefault(_k, _v)

import asyncio  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from collections.abc import AsyncIterator, Callable  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from jwt.algorithms import ECAlgorithm  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()


# ---------------------------------------------------------------- event loop
@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    import sys

    # psycopg (LangGraph checkpointer) cannot run on Windows' Proactor loop
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
    return asyncio.DefaultEventLoopPolicy()


# ---------------------------------------------------------------- database
def _admin_url() -> str:
    base, _, _ = TEST_DB.rpartition("/")
    return base + "/postgres"


async def _ensure_db() -> None:
    dbname = TEST_DB.rpartition("/")[2]
    eng = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        exists = await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": dbname})
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    await eng.dispose()


def _migrate() -> None:
    from alembic.config import Config

    from alembic import command

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    command.upgrade(cfg, "head")


KEEP_TABLES = {"plans", "categories", "alembic_version"}
_DIRTY = {"db": True, "installed": False}


def _install_write_tracker(eng: Any) -> None:
    if _DIRTY["installed"]:
        return
    from sqlalchemy import event

    @event.listens_for(eng.sync_engine, "before_cursor_execute")
    def _track(conn: Any, cursor: Any, statement: str, *a: Any) -> None:
        head = statement.lstrip()[:10].upper()
        if head.startswith(("INSERT", "UPDATE", "DELETE", "WITH", "TRUNCATE")):
            _DIRTY["db"] = True

    _DIRTY["installed"] = True


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _database() -> AsyncIterator[None]:
    await _ensure_db()
    await asyncio.to_thread(_migrate)
    yield
    from app.core.db import dispose_engine
    from app.core.redis import close_redis
    from app.fetch.client import close_http_client
    from app.workers.queue import close_pool

    await close_http_client()
    await close_pool()
    await close_redis()
    await dispose_engine()


@pytest_asyncio.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    from app.core.db import get_engine
    from app.core.redis import get_redis
    from app.models import Base
    from app.services.plans import invalidate_plan_cache

    eng = get_engine()
    _install_write_tracker(eng)
    tables = [t.name for t in Base.metadata.sorted_tables if t.name not in KEEP_TABLES]
    if not _DIRTY["db"]:
        await get_redis().flushdb()
        invalidate_plan_cache()
        yield
        return
    _DIRTY["db"] = False
    async with eng.begin() as conn:
        await conn.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
        await conn.execute(text(
            "INSERT INTO profiles (id, email_verified, display_name, handle, timezone, locale, plan_id, role, status, "
            "digest_time, default_channels, default_delivery_mode, max_alerts_per_hour, auto_tune, "
            "email_alerts_enabled, marketing_opt_in, abuse_score) VALUES ('00000000-0000-0000-0000-000000000001', "
            "true, 'Watchtower Community', 'community', 'Asia/Kolkata', 'en-IN', 'pro', 'user', 'active', '08:00', "
            "'[]', 'instant', 0, true, false, false, 0)"
        ))
    _DIRTY["db"] = False
    await get_redis().flushdb()
    invalidate_plan_cache()
    yield


# ---------------------------------------------------------------- fixture web server
@dataclass
class Route:
    status: int = 200
    body: bytes | str = b""
    headers: dict[str, str] = field(default_factory=lambda: {"Content-Type": "text/html; charset=utf-8"})
    delay: float = 0.0


class FixtureSite:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.hits: dict[str, int] = {}
        self.requests: list[dict[str, Any]] = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _serve(self) -> None:
                host = (self.headers.get("Host") or "").split(":")[0]
                key = f"{host}{self.path}"
                site.hits[key] = site.hits.get(key, 0) + 1
                site.requests.append({"key": key, "headers": dict(self.headers)})
                route = site.routes.get(key) or site.routes.get(self.path)
                if route is None:
                    if self.path == "/robots.txt":
                        route = Route(404, b"")
                    else:
                        route = Route(404, b"<html><body>Not found</body></html>")
                if route.delay:
                    time.sleep(route.delay)
                body = route.body.encode() if isinstance(route.body, str) else route.body
                inm = self.headers.get("If-None-Match")
                if inm and route.headers.get("ETag") == inm and route.status == 200:
                    self.send_response(304)
                    self.end_headers()
                    return
                self.send_response(route.status)
                for k, v in route.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = _serve  # noqa: N815
            do_POST = _serve  # noqa: N815

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, host: str, path: str = "/") -> str:
        return f"http://{host}:{self.port}{path}"

    def set(self, host: str, path: str, body: str | bytes, status: int = 200, headers: dict[str, str] | None = None,
            delay: float = 0.0) -> str:
        h = {"Content-Type": "text/html; charset=utf-8"}
        if headers:
            h.update(headers)
        self.routes[f"{host}{path}"] = Route(status, body, h, delay)
        return self.url(host, path)

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture(scope="session")
def site() -> Any:
    from app.fetch.ssrf import set_resolver

    s = FixtureSite()

    async def resolver(host: str, port: int) -> list[str]:
        if host.endswith(".test"):
            return ["127.0.0.1"]
        if host == "rebind.example.com":
            return ["10.0.0.5"]
        if host == "mixed.example.com":
            return ["93.184.216.34", "127.0.0.1"]
        if host == "public.example.com":
            return ["93.184.216.34"]
        raise OSError("no such host in tests")

    set_resolver(resolver)
    yield s
    set_resolver(None)
    s.close()


@pytest.fixture(autouse=True)
def _reset_site(site: FixtureSite) -> None:
    site.routes.clear()
    site.hits.clear()
    site.requests.clear()


# ---------------------------------------------------------------- fake LLM
class FakeLLM:
    """Scriptable LLM. handlers[purpose](system, user) -> dict (validated against the schema like the real one)."""

    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[str, str], dict[str, Any]]] = {}
        self.calls: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None

    def on(self, purpose: str, fn: Callable[[str, str], dict[str, Any]] | dict[str, Any]) -> None:
        self.handlers[purpose] = fn if callable(fn) else (lambda s, u, _v=fn: _v)

    def count(self, purpose: str | None = None) -> int:
        return len([c for c in self.calls if purpose is None or c["purpose"] == purpose])

    async def structured(self, *, purpose: str, tier: str, system: str, user: str, schema: Any,
                         user_id: Any = None, plan_id: str = "free", max_tokens: int = 1500,
                         temperature: float = 0.1, cache: bool = True, token_limit_per_day: int | None = None) -> Any:
        from app.llm.client import LLMResult

        self.calls.append({"purpose": purpose, "tier": tier, "system": system, "user": user, "user_id": user_id})
        if self.fail_with is not None:
            raise self.fail_with
        if purpose not in self.handlers:
            raise AssertionError(f"FakeLLM has no handler for purpose={purpose!r}")
        data = self.handlers[purpose](system, user)
        return LLMResult(data=schema.model_validate(data), model=f"fake-{tier}", prompt_tokens=100,
                         completion_tokens=50, cost_usd=0.0001)


@pytest.fixture
def llm() -> Any:
    from app.llm.client import set_llm

    fake = FakeLLM()
    set_llm(fake)
    yield fake
    set_llm(None)


# ---------------------------------------------------------------- auth / users
@dataclass
class AuthKit:
    private_key: Any
    kid: str

    def token(self, user_id: uuid.UUID, email: str = "user@example.com", *, verified: bool = True,
              admin: bool = False, exp_in: int = 3600, **overrides: Any) -> str:
        import jwt

        now = int(time.time())
        claims = {
            "sub": str(user_id), "email": email, "aud": "authenticated", "role": "authenticated",
            "iss": "https://proj.supabase.co/auth/v1", "iat": now, "exp": now + exp_in,
            "app_metadata": {"provider": "email", **({"role": "admin"} if admin else {})},
            "user_metadata": {"email_verified": verified}, "is_anonymous": False,
        }
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="ES256", headers={"kid": self.kid})


@pytest.fixture(scope="session")
def auth_kit() -> AuthKit:
    from app.core.auth import jwks_cache

    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(ECAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "test-kid", "alg": "ES256", "use": "sig"})
    jwks_cache.set_static({"keys": [jwk]})
    return AuthKit(private_key=key, kid="test-kid")


@pytest_asyncio.fixture
async def make_user() -> Callable[..., Any]:
    from app.core.db import session_scope
    from app.models import Profile

    async def _make(plan: str = "free", email: str | None = None, verified: bool = True, **kw: Any) -> Profile:
        uid = uuid.uuid4()
        async with session_scope() as s:
            p = Profile(id=uid, email=email or f"u{uid.hex[:8]}@example.com", email_verified=verified, plan_id=plan,
                        **kw)
            s.add(p)
        async with session_scope() as s:
            p = await s.get(Profile, uid)
            s.expunge(p)
            return p

    return _make


# ---------------------------------------------------------------- API client + inline job runner
@pytest_asyncio.fixture
async def client() -> AsyncIterator[Any]:
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as c:
        yield c


@pytest.fixture
def auth(auth_kit: AuthKit) -> Callable[..., dict[str, str]]:
    def _h(user: Any, **kw: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {auth_kit.token(user.id, user.email or 'x@example.com', **kw)}"}

    return _h


async def drain(queues: tuple[str, ...] = ("checks", "agents", "notify"), *, max_jobs: int = 500,
                include_deferred: bool = True, only: set[str] | None = None) -> list[tuple[str, Any]]:
    """Execute queued arq jobs inline (deterministic e2e tests). Returns [(function, result)]."""
    from arq.jobs import deserialize_job

    from app.core.redis import get_redis
    from app.workers.main import QUEUE_CONFIG

    funcs = {f.__name__: f for cfg in QUEUE_CONFIG.values() for f in cfg["functions"]}
    r = get_redis()
    from redis.asyncio import Redis

    raw = Redis.from_url(TEST_REDIS)  # bytes client: arq pickles jobs
    done: list[tuple[str, Any]] = []
    try:
        for _ in range(max_jobs):
            progressed = False
            for qname in queues:
                qkey = QUEUE_CONFIG[qname]["queue"]
                now_ms = int(time.time() * 1000)
                ids = await raw.zrangebyscore(qkey, "-inf", "+inf" if include_deferred else now_ms, start=0, num=1)
                if not ids:
                    continue
                job_id = ids[0].decode()
                await raw.zrem(qkey, job_id)
                data = await raw.get(f"arq:job:{job_id}")
                await raw.delete(f"arq:job:{job_id}")
                if data is None:
                    continue
                jd = deserialize_job(data)
                if only is not None and jd.function not in only:
                    continue
                fn = funcs[jd.function]
                done.append((jd.function, await fn({}, *jd.args, **jd.kwargs)))
                progressed = True
            if not progressed:
                break
    finally:
        await raw.aclose()
    _ = r
    return done


@pytest.fixture
def run_jobs() -> Callable[..., Any]:
    return drain


async def emails() -> list[dict[str, Any]]:
    from app.core.redis import get_redis

    return [json.loads(x) for x in await get_redis().lrange("outbox:email", 0, -1)]


@pytest.fixture
def sent_emails() -> Callable[..., Any]:
    return emails
