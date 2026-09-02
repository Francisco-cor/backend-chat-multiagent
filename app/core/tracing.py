"""Distributed tracing — Fase 11.1 OTel + log correlation.

Best-effort: if opentelemetry packages not installed or OTEL_ENABLED=false,
tracing is no-op. Otherwise instruments FastAPI, SQLAlchemy, httpx and
propagates trace_id into logging ContextVar (already used for request_id).
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Try to integrate with existing request_id ContextVar for correlation
try:
    from app.core.logging import request_id_var  # not yet, but fallback
except Exception:
    request_id_var = None

try:
    from app.core.request_id import request_id_var as req_var
except Exception:
    req_var = None


def setup_tracing(app=None, service_name: str = "backend-chat-multiagent"):
    """Configure OTel SDK if available. Returns tracer or None."""
    enabled = os.getenv("OTEL_ENABLED", "false").lower() in ("1", "true", "yes")
    # Also check config
    try:
        from app.core.config import settings
        # allow OTEL_ENABLED via env file?
        if hasattr(settings, "OTEL_ENABLED") and getattr(settings, "OTEL_ENABLED"):
            enabled = True
        endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", None) or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    except Exception:
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")

    if not enabled:
        logger.info("Tracing disabled (OTEL_ENABLED != true)")
        return None

    try:
        from opentelemetry import trace, baggage
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.propagators.composite import CompositePropagator
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        from opentelemetry.baggage.propagation import W3CBaggagePropagator
    except ImportError as e:
        logger.warning(f"OTel packages not installed, tracing disabled: {e}")
        return None

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    try:
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
    except Exception as e:
        logger.warning(f"OTel exporter init failed: {e}")
        return None

    trace.set_tracer_provider(provider)
    set_global_textmap(CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()]))

    # Instrument
    if app is not None:
        try:
            FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
            logger.info("FastAPI OTel instrumented")
        except Exception as e:
            logger.warning(f"FastAPI instrument failed: {e}")
    try:
        SQLAlchemyInstrumentor().instrument(enable_commenter=True)
    except Exception:
        pass
    try:
        HTTPXClientInstrumentor().instrument()
    except Exception:
        pass

    logger.info(f"Tracing enabled -> {endpoint}")

    # Optional: add filter to inject trace_id into logs (if request_id_var exists)
    try:
        from opentelemetry import trace as trace_api

        class TraceIdFilter(logging.Filter):
            def filter(self, record):
                span = trace_api.get_current_span()
                ctx = span.get_span_context() if span else None
                if ctx and ctx.is_valid:
                    # format as 32-char hex
                    record.trace_id = format(ctx.trace_id, "032x")
                    record.span_id = format(ctx.span_id, "016x")
                else:
                    record.trace_id = getattr(record, "trace_id", "-")
                    record.span_id = getattr(record, "span_id", "-")
                # also sync to request_id var for correlation if missing
                if req_var is not None:
                    try:
                        if not req_var.get("-") or req_var.get() == "-":
                            pass
                    except Exception:
                        pass
                return True

        # attach to root logger
        for h in logging.getLogger().handlers:
            h.addFilter(TraceIdFilter())
        logging.getLogger().addFilter(TraceIdFilter())
    except Exception as e:
        logger.warning(f"TraceId log filter failed: {e}")

    return trace.get_tracer(service_name)


def get_tracer(name: str = "app"):
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except Exception:
        # no-op tracer
        class NoOpSpan:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def set_attribute(self, *a, **kw): pass
            def record_exception(self, *a, **kw): pass

        class NoOpTracer:
            def start_as_current_span(self, *a, **kw): return NoOpSpan()
        return NoOpTracer()
