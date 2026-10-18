"""OpenTelemetry tracing (enabled when WT_OTEL_EXPORTER_OTLP_ENDPOINT is set)."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
_configured = False


def setup_tracing(service_name: str | None = None, app: Any = None, engine: Any = None) -> bool:
    global _configured
    s = get_settings()
    if not s.otel_exporter_otlp_endpoint:
        return False
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    if not _configured:
        provider = TracerProvider(resource=Resource.create({"service.name": service_name or s.otel_service_name,
                                                            "deployment.environment": s.env}))
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=s.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"))
        )
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument()
        _configured = True
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
    if engine is not None:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    log.info("tracing_enabled", endpoint=s.otel_exporter_otlp_endpoint)
    return True


def tracer(name: str = "watchtower") -> Any:
    from opentelemetry import trace

    return trace.get_tracer(name)
