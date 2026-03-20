import uuid
import logging
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Module-level ContextVar so any logger in any coroutine can read the current request ID.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assigns a unique ID to every request.
    - Reads X-Request-ID from the incoming headers if present (useful for
      propagating IDs from a gateway/load balancer).
    - Falls back to a new UUID4.
    - Stores the ID in request.state.request_id and in request_id_var so all
      loggers downstream automatically include it.
    - Echoes the ID back in the X-Request-ID response header.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


class RequestIDFilter(logging.Filter):
    """Injects the current request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")
        return True
