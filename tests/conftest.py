import os
import pytest
from typing import AsyncGenerator

# Set dummy env vars before importing app (Settings validates at import)
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-long-12345")

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.session import get_db
from app.main import app

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

TestingSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


_tables_created = False


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    global _tables_created
    if not _tables_created:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _tables_created = True
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def clear_caches():
    # Clear LLM/embedding caches and redis fallback between tests
    try:
        from app.services.cache_service import cache_service
        cache_service._mem.clear()
        cache_service._mem_embedding.clear()
        # also clear redis sliding window fallback
        from app.core.rate_limit import redis_sliding_window
        redis_sliding_window._fallback_store.clear()
        # clear stream buffers
        from app.services.stream_manager import _buffers, _counters
        _buffers.clear()
        _counters.clear()
    except Exception:
        pass
    yield


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    # Disable rate limiting for tests (in-memory limiter would hit 3/min across tests)
    original_enabled = getattr(app.state.limiter, "enabled", True)
    app.state.limiter.enabled = False
    # Also reset storage if available
    try:
        app.state.limiter.storage.reset()  # type: ignore[attr-defined]
    except Exception:
        pass
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    app.state.limiter.enabled = original_enabled


@pytest.fixture
async def auth_headers(client: AsyncClient):
    """Register a user and return Authorization headers."""
    import secrets

    email = f"user_{secrets.token_hex(4)}@example.com"
    password = "TestPass123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
