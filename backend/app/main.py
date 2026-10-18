"""FastAPI application factory: middleware (request ids, metrics, security headers, body limits, per-IP limits),
uniform error envelope, health/readiness/metrics, and the v1 API."""

from __future__ import annotations

import hmac
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import (
    admin,
    alerts,
    auth,
    explore,
    intake,
    me,
    notifications,
    public,
    stream,
    watches,
    webhooks,
)
from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.core.errors import AppError, RateLimited, error_body
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis, get_redis, sliding_window_allow
from app.fetch.client import close_http_client
from app.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.observability.tracing import setup_tracing
from app.workers.queue import close_pool

log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    setup_tracing("watchtower-api", app=app, engine=get_engine())
    log.info("api_started", env=s.env)
    yield
    from app.services.intake import close_intake_graph

    await close_intake_graph()
    await close_http_client()
    await close_pool()
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Watchtower API", version="1.0.0", lifespan=lifespan,
        description="AI agents that watch the web for you. India-first, community-powered.",
        docs_url="/docs" if s.env != "prod" else None, redoc_url=None,
        openapi_url="/openapi.json" if s.env != "prod" else None,
    )

    @app.middleware("http")
    async def core_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id", "")
        rid = rid if (rid and len(rid) <= 64 and rid.replace("-", "").isalnum()) else uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        request.state.request_id = rid
        started = time.perf_counter()
        # body size guard (content-length; streaming bodies are also capped by Starlette reads in handlers)
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > s.max_request_body_bytes:
            return JSONResponse(error_body("payload_too_large", "Request body too large", request_id=rid), status_code=413)
        # coarse per-IP ceiling for everything (route-specific limits are tighter)
        if request.url.path not in ("/healthz", "/readyz", "/metrics"):
            ip = request.client.host if request.client else "unknown"
            try:
                ok, retry = await sliding_window_allow(f"rl:global:{ip}", 600, 60)
            except Exception:
                ok, retry = True, 0  # never fail closed on the limiter itself
            if not ok:
                return JSONResponse(error_body("rate_limited", "Too many requests", request_id=rid), status_code=429,
                                    headers={"Retry-After": str(retry)})
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled_error", path=request.url.path)
            response = JSONResponse(error_body("internal_error", "Something went wrong", request_id=rid), status_code=500)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        elapsed = time.perf_counter() - started
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, path).observe(elapsed)
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if s.env == "prod":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if path.startswith("/v1") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        if response.status_code >= 500 or elapsed > 2:
            log.info("http_request", method=request.method, path=path, status=response.status_code,
                     ms=int(elapsed * 1000))
        return response

    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"], max_age=600,
    )

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimited) else None
        return JSONResponse(error_body(exc.code, exc.message, exc.details, getattr(request.state, "request_id", None)),
                            status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()[:20]]
        return JSONResponse(error_body("validation_failed", "Invalid request", details,
                                       getattr(request.state, "request_id", None)), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail), None, getattr(request.state, "request_id", None)),
                            status_code=exc.status_code)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"error: {type(e).__name__}"
        try:
            await get_redis().ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {type(e).__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        token = s.metrics_token.get_secret_value()
        if token:
            auth_h = request.headers.get("authorization", "")
            if not hmac.compare_digest(auth_h, f"Bearer {token}"):
                return Response(status_code=401)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    for r in (auth.router, me.router, intake.router, watches.router, alerts.router, explore.router,
              notifications.router, stream.router, public.router, webhooks.router, admin.router):
        app.include_router(r, prefix="/v1")
    return app


app = create_app()
