import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from app.core.logging import configure_logging
from app.core.request_id import RequestIDMiddleware
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command
from app.api.v1.api import api_router
from app.db.session import engine
from app.core.config import settings
from app.core.rate_limit import limiter
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from google import genai
from openai import AsyncOpenAI
import anthropic

configure_logging(json_logs=settings.JSON_LOGS)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 STARTUP: Booting system...")
    logger.info(f"🐍 Python {sys.version}")

    # 1) Run Alembic migrations — fatal: app cannot serve requests without a DB.
    try:
        def _run_migrations():
            cfg = AlembicConfig("alembic.ini")
            alembic_command.upgrade(cfg, "head")

        await asyncio.to_thread(_run_migrations)
        logger.info("✅ DB: Migrations applied.")
    except Exception as e:
        logger.critical(f"❌ DB MIGRATION ERROR: {e}")
        sys.exit(1)

    # 2) Google GenAI (SDK 2025 Check)
    try:
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY missing")
        genai.Client(api_key=settings.GOOGLE_API_KEY)
        logger.info("✅ Google GenAI Client (v1.51+): Configured.")
    except Exception as e:
        logger.error(f"❌ Google Client Error: {e}")

    # 3) OpenAI check
    if settings.OPENAI_API_KEY:
        try:
            app.state.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            logger.info("✅ OpenAI Client: Ready.")
        except Exception as e:
            logger.error(f"❌ OpenAI Error: {e}")
            app.state.openai_client = None

    # 4) Anthropic check
    if settings.ANTHROPIC_API_KEY:
        try:
            anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            logger.info("✅ Anthropic Client: Ready.")
        except Exception as e:
            logger.error(f"❌ Anthropic Error: {e}")

    yield  # app runs here


app = FastAPI(
    title="Chatbot API (GenAI 2025 Standard)",
    description="Backend with google-genai v1.51 (Gemini 2.5/3.0) and GPT-5.",
    version="3.5.0",
    lifespan=lifespan,
)

# Connect Limiter to the app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(RequestIDMiddleware)

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

# Include the API router
app.include_router(api_router, prefix="/api/v1")

@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness + readiness probe. Verifies DB connectivity."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/", tags=["Root"])
def read_root():
    return {
        "status": "online",
        "stack": "FastAPI + Google GenAI SDK 1.51",
    }
