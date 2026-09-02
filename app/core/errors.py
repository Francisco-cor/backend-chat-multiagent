"""RFC 7807 Problem Details for HTTP APIs — Fase 10.1"""
import logging
import traceback
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi.errors import RateLimitExceeded

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ProblemDetail(BaseModel):
    """RFC 7807 https://datatracker.ietf.org/doc/html/rfc7807"""
    type: str = Field(default="about:blank", examples=["https://api.example.com/errors/validation"])
    title: str = Field(..., examples=["Validation Error", "Rate Limit Exceeded"])
    status: int = Field(..., examples=[422, 429, 500])
    detail: str | None = Field(None, examples=["Field 'prompt' is required"])
    instance: str | None = Field(None, examples=["/api/v1/chat/"])
    # extensions
    code: str | None = Field(None, examples=["VALIDATION_ERROR"])
    errors: Any | None = None
    headers: dict | None = None


def _problem_response(
    request: Request,
    status_code: int,
    title: str,
    detail: str | None = None,
    type_url: str = "about:blank",
    code: str | None = None,
    errors: Any | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    payload = ProblemDetail(
        type=type_url,
        title=title,
        status=status_code,
        detail=detail,
        instance=str(request.url.path),
        code=code,
        errors=errors,
    ).model_dump(exclude_none=True)
    # also include correlation id if present
    req_id = request.headers.get("x-request-id") or getattr(request.state, "request_id", None)
    if req_id:
        payload["request_id"] = req_id
    # Per RFC 7807 content-type
    resp_headers = {"Content-Type": "application/problem+json"}
    if headers:
        resp_headers.update(headers)
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload), headers=resp_headers)


def setup_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Preserve headers like WWW-Authenticate, Retry-After
        headers = getattr(exc, "headers", None)
        # Map to title
        title_map = {
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            409: "Conflict",
            413: "Payload Too Large",
            422: "Unprocessable Entity",
            423: "Locked",
            429: "Too Many Requests",
            500: "Internal Server Error",
            503: "Service Unavailable",
        }
        title = title_map.get(exc.status_code, f"HTTP {exc.status_code}")
        detail = str(exc.detail) if exc.detail else None
        # If detail is already a ProblemDetail-like dict with extensions, pass through
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            detail = str(exc.detail)
            errors = exc.detail
        else:
            errors = None
        # Ensure Retry-After etc. forwarded
        extra_headers = {}
        if headers:
            extra_headers.update(headers)
        # If exc has headers containing Retry-After from quota/rate-limit
        return _problem_response(
            request,
            status_code=exc.status_code,
            title=title,
            detail=detail,
            code=f"HTTP_{exc.status_code}",
            errors=errors,
            headers=extra_headers if extra_headers else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        # Build readable detail from first error, keep full list in extension
        first = errors[0] if errors else {}
        loc = ".".join(str(x) for x in first.get("loc", []))
        msg = first.get("msg", "Validation failed")
        detail = f"{loc}: {msg}" if loc else msg
        return _problem_response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Validation Error",
            detail=detail,
            type_url="https://api.example.com/errors/validation",
            code="VALIDATION_ERROR",
            errors=errors,
        )

    @app.exception_handler(RateLimitExceeded)
    async def ratelimit_handler(request: Request, exc: RateLimitExceeded):
        # slowapi raises this; we map to RFC 7807 429
        detail = getattr(exc, "detail", None) or "Rate limit exceeded"
        # Try to get Retry-After from exc
        headers = {"Retry-After": "60"}
        return _problem_response(
            request,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            title="Too Many Requests",
            detail=str(detail),
            type_url="https://api.example.com/errors/rate-limit",
            code="RATE_LIMITED",
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled exception: {exc}\n{traceback.format_exc()}")
        return _problem_response(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Internal Server Error",
            detail="An unexpected error occurred. Please try again later.",
            type_url="https://api.example.com/errors/internal",
            code="INTERNAL_ERROR",
        )
