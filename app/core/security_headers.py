from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from typing import Callable


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds security headers to every response:
    - HSTS (only if HTTPS)
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 0
    - Referrer-Policy
    - CSP (basic)
    - Permissions-Policy
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        # Prevent MIME sniffing
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Clickjacking protection
        response.headers.setdefault("X-Frame-Options", "DENY")
        # XSS filter disable (modern browsers)
        response.headers.setdefault("X-XSS-Protection", "0")
        # Referrer policy
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Minimal CSP — allow self, inline styles for Swagger/ReDoc, and API
        # Adjust in production if serving frontend from different origin
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https:; frame-ancestors 'none'",
        )
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # HSTS only if request is HTTPS (or behind proxy with X-Forwarded-Proto)
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        scheme = request.url.scheme
        if scheme == "https" or forwarded_proto == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload"
            )
        return response
