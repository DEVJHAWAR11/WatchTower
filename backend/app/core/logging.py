"""Structured logging with contextvars (request_id, user_id, run_id, ...) and PII redaction."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_SECRET_KEYS = {
    "authorization", "password", "token", "access_token", "refresh_token", "api_key", "secret",
    "cookie", "set-cookie", "p256dh", "auth", "service_role_key",
}


def _mask_email(m: re.Match[str]) -> str:
    local = m.group(1)
    return f"{local[:1]}***@{m.group(2)}"


def redact(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return value
    if isinstance(value, str):
        return _EMAIL_RE.sub(_mask_email, value)
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if str(k).lower() in _SECRET_KEYS else redact(v, depth + 1)) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v, depth + 1) for v in value]
    return value


def _redaction_processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return {k: ("[redacted]" if k.lower() in _SECRET_KEYS else redact(v)) for k, v in event_dict.items()}


def _add_trace_ids(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except Exception:  # noqa: S110 - tracing is best-effort
        pass
    return event_dict


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_trace_ids,
        _redaction_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping().get(level.upper(), 20)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(levelname)s %(name)s %(message)s")
    for noisy in ("httpx", "httpcore", "asyncio", "arq.jobs"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
