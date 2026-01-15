import logging
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.api import api_router
from app.db.base import Base
from app.db.session import engine
from app.core.config import settings
from openai import OpenAI

# IMPORT SDK NUEVO
from app.core.config import settings
from app.core.rate_limit import limiter
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

app = FastAPI(
    title="Chatbot API (GenAI 2025 Standard)",
    description="Backend con google-genai v1.51 (Gemini 2.5/3.0) y GPT-5.",
    version="3.5.0",
)

# Conectar Limiter a la app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup() -> None:
    logger.info("🚀 INICIO: Booting system...")
    logger.info(f"🐍 Python {sys.version}")

    # 1) DB
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ DB: Tablas sincronizadas.")
    except Exception as e:
        logger.critical(f"❌ DB ERROR: {e}")

    # 2) Google GenAI (SDK 2025 Check)
    try:
        if not settings.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY missing")
        # Prueba simple de instanciación del cliente
        client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        logger.info("✅ Google GenAI Client (v1.51+): Configurado.")
    except Exception as e:
        logger.error(f"❌ Google Client Error: {e}")

    # 3) OpenAI
    if settings.OPENAI_API_KEY:
        try:
            app.state.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
            logger.info("✅ OpenAI Client: Listo.")
        except Exception as e:
            logger.error(f"❌ OpenAI Error: {e}")
            app.state.openai_client = None

# --- CORRECCIÓN AQUÍ ---
# Quitamos el '@' y dejamos la llamada sola.
app.include_router(api_router, prefix="/api/v1")

@app.get("/", tags=["Root"])
def read_root():
    return {
        "status": "online",
        "stack": "FastAPI + Google GenAI SDK 1.51",
        "models": settings.ALLOWED_MODELS
    }