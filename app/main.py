import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.api import api_router
from app.db.base import Base
from app.db.session import engine
from app.core.config import settings
from app.core.rate_limit import limiter
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from google import genai
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 STARTUP: Booting system...")
    logger.info(f"🐍 Python {sys.version}")

    # 1) Database initialization — fatal: app cannot serve requests without a DB.
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ DB: Tables synchronized.")
    except Exception as e:
        logger.critical(f"❌ DB ERROR: {e}")
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
            app.state.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
            logger.info("✅ OpenAI Client: Ready.")
        except Exception as e:
            logger.error(f"❌ OpenAI Error: {e}")
            app.state.openai_client = None

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

@app.get("/", tags=["Root"])
def read_root():
    return {
        "status": "online",
        "stack": "FastAPI + Google GenAI SDK 1.51",
        "models": settings.ALLOWED_MODELS
    }
