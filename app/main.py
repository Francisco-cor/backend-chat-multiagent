import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager
from app.core.logging import configure_logging
from app.core.request_id import RequestIDMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command
from app.api.v1.api import api_router
from app.db.session import engine
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.metrics import setup_metrics
from app.core.errors import setup_problem_handlers
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from google import genai
from openai import AsyncOpenAI
import anthropic

configure_logging(json_logs=settings.JSON_LOGS)
logger = logging.getLogger("main")

_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("STARTUP: Booting system...")
    logger.info(f"Python {sys.version}")

    # 1) Run Alembic migrations — idempotent, fatal only if DB unreachable after retries
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            def _run_migrations():
                cfg = AlembicConfig("alembic.ini")
                alembic_command.upgrade(cfg, "head")

            await asyncio.to_thread(_run_migrations)
            logger.info("DB: Migrations applied.")
            break
        except Exception as e:
            logger.warning(f"DB migration attempt {attempt}/{max_retries} failed: {e}")
            if attempt == max_retries:
                logger.critical(f"DB MIGRATION ERROR after {max_retries} attempts: {e}")
                sys.exit(1)
            await asyncio.sleep(2 * attempt)

    # 2) Google GenAI (SDK 2025 Check)
    try:
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY missing")
        genai.Client(api_key=settings.GOOGLE_API_KEY)
        logger.info("Google GenAI Client (v1.51+): Configured.")
    except Exception as e:
        logger.error(f"Google Client Error: {e}")

    # 3) OpenAI check
    if settings.OPENAI_API_KEY:
        try:
            app.state.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            logger.info("OpenAI Client: Ready.")
        except Exception as e:
            logger.error(f"OpenAI Error: {e}")
            app.state.openai_client = None

    # 4) Anthropic check
    if settings.ANTHROPIC_API_KEY:
        try:
            # Store in app.state for reuse (aligns with OpenAI handling)
            app.state.anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            logger.info("Anthropic Client: Ready.")
        except Exception as e:
            logger.error(f"Anthropic Error: {e}")
            app.state.anthropic_client = None
    else:
        app.state.anthropic_client = None

    # 5) Load builtin tools
    try:
        from app.tools.registry import load_builtin_tools, tool_registry

        load_builtin_tools()
        logger.info(f"Tools loaded: {tool_registry.list_names()}")
    except Exception as e:
        logger.warning(f"Tool loading failed: {e}")

    # 6) Load MCP servers (best-effort)
    if settings.MCP_SERVERS:
        try:
            from app.mcp.registry import mcp_registry

            for srv in settings.MCP_SERVERS:
                mcp_registry.add_server(srv.get("name"), srv.get("url"), srv.get("transport", "sse"))
            # Don't block startup on MCP
            try:
                await mcp_registry.load_tools()
            except Exception as e:
                logger.warning(f"MCP load failed: {e}")
        except Exception as e:
            logger.warning(f"MCP registry failed: {e}")

    # 7) Redis check (best-effort)
    if settings.REDIS_URL:
        try:
            import redis.asyncio as redis  # type: ignore

            r = redis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.ping()
            app.state.redis = r
            logger.info("Redis: Connected.")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            app.state.redis = None
    else:
        app.state.redis = None

    yield  # app runs here

    # Graceful shutdown
    try:
        if hasattr(app.state, "redis") and app.state.redis:
            await app.state.redis.close()
    except Exception:
        pass


app = FastAPI(
    title="Chatbot API (GenAI 2025 Standard)",
    description="Backend with google-genai v1.51 (Gemini 2.5/3.0) and GPT-5. Multi-agent orchestration, RAG, tools, streaming.",
    version="3.5.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "auth", "description": "JWT + refresh + API keys. Use `POST /auth/login` then `Authorization: Bearer <jwt>` or `X-API-Key: sk_...`"},
        {"name": "chat", "description": "Direct LLM + streaming (SSE resilient, WS). Quota + rate-limit via Redis; writes UsageLedger."},
        {"name": "conversations", "description": "Conversations ↔ messages CRUD, cursor pagination, soft-delete, legacy `session_id` alias."},
        {"name": "documents", "description": "RAG ingest (pdf/txt/md → chunk → embed) + retrieve."},
        {"name": "files", "description": "S3/MinIO presigned upload."},
        {"name": "api-keys", "description": "API key lifecycle (hash + scopes + expiry). Scopes: chat:write/read, etc."},
        {"name": "billing", "description": "Usage ledger + cost aggregation + Stripe webhook stub."},
        {"name": "admin", "description": "Superuser only (list users, quotas, ban, plan)."},
        {"name": "ws", "description": "WebSocket `/ws/chat?token=<jwt>` ping/pong, ack, delta streaming."},
        {"name": "Health", "description": "Liveness `/health/live` (process) vs readiness `/health/ready` (DB+Redis)."},
        {"name": "Metrics", "description": "Prometheus `/metrics`."},
    ],
    contact={"name": "Clara Platform", "url": "https://github.com/Francisco-cor/backend-chat-multiagent"},
    license_info={"name": "MIT"},
)

# Connect Limiter to the app (RFC7807 handler will override 429 formatting; keep slowapi fallback)
app.state.limiter = limiter
# Keep fallback then override with ProblemDetails
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
setup_problem_handlers(app)

# --- OpenAPI security schemes (JWT + API-Key) ---
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    # Ensure components/securitySchemes exist
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    openapi_schema["components"]["securitySchemes"]["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "JWT from POST /api/v1/auth/login (`Authorization: Bearer <jwt>`) or `?token=` for WS.",
    }
    openapi_schema["components"]["securitySchemes"]["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API key `sk_...` from POST /api/v1/api-keys. Also accepted as `Authorization: Bearer sk_...`. Scopes: chat:write etc.",
    }
    # Apply bearer to most paths (optional, not forced)
    openapi_schema["security"] = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
    # Add problem+json example to 422/429
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi  # type: ignore[method-assign]

# Metrics inner to CORS but outer to route — added first
setup_metrics(app)

# allow_credentials=True is unsafe with wildcard origins (any domain could hijack auth).
# Only enable it when specific trusted origins are configured.
_allow_credentials = "*" not in settings.CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Security headers and request ID outermost — added last so they wrap all
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)

# Include the API router
app.include_router(api_router, prefix="/api/v1")
# Also mount WS at root for spec compliance (client expects /ws/chat not /api/v1/ws/chat)
from app.api.v1.endpoints.ws import router as ws_router  # noqa: E402

app.include_router(ws_router)

# Playground static (Fase 10.4) — serve /playground if directory exists
try:
    from fastapi.staticfiles import StaticFiles
    import os as _os

    _play = _os.path.join(_os.path.dirname(__file__), "..", "playground")
    if _os.path.isdir(_play):
        app.mount("/playground", StaticFiles(directory=_play, html=True), name="playground")
        logger.info("Playground mounted at /playground")
except Exception as e:
    logger.warning(f"Playground mount failed: {e}")


@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness + readiness probe. Verifies DB connectivity. (Legacy compat — delegates to /health/live)"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/health/live", tags=["Health"])
async def health_live():
    """Liveness: process is running."""
    uptime = time.time() - _start_time
    return {"status": "alive", "uptime_seconds": round(uptime, 2)}


@app.get("/health/ready", tags=["Health"])
async def health_ready():
    """Readiness: DB + Redis (if configured) must be reachable."""
    checks = {}
    # DB
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        logger.warning(f"Readiness DB failed: {e}")
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": {"database": "disconnected"}})
    # Redis if configured
    if settings.REDIS_URL:
        try:
            r = getattr(app.state, "redis", None)
            if r is None:
                import redis.asyncio as redis  # type: ignore

                r = redis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.ping()
            checks["redis"] = "connected"
        except Exception as e:
            logger.warning(f"Readiness Redis failed: {e}")
            raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": {**checks, "redis": "disconnected"}})
    else:
        checks["redis"] = "not_configured"
    return {"status": "ready", "checks": checks}


@app.get("/", tags=["Root"])
def read_root():
    return {
        "status": "online",
        "stack": "FastAPI + Google GenAI SDK 1.51",
    }
