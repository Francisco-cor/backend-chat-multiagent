import logging
import time
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

LLM_REQUESTS = Counter(
    "llm_requests_total",
    "Total LLM provider calls",
    ["provider", "model", "status"],
)

LLM_LATENCY = Histogram(
    "llm_request_duration_seconds",
    "LLM request latency",
    ["provider", "model"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        # Normalize endpoint to avoid cardinality explosion (use route path)
        endpoint = request.url.path
        # Try to get matched route
        try:
            route = request.scope.get("route")
            if route and hasattr(route, "path"):
                endpoint = route.path
        except Exception:
            pass

        response = None
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            elapsed = time.perf_counter() - start
            # Don't count /metrics itself to avoid recursion noise
            if endpoint != "/metrics":
                REQUEST_COUNT.labels(method=request.method, endpoint=endpoint, status=status).inc()
                REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(elapsed)


def setup_metrics(app: FastAPI) -> None:
    app.add_middleware(MetricsMiddleware)

    @app.get("/metrics", tags=["Metrics"], include_in_schema=False)
    def metrics():
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
