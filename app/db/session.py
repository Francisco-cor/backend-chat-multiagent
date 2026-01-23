from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Asynchronous database engine
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

# Asynchronous session factory
# Note: expire_on_commit=False prevents lazy loading issues after commit
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)

# Dependency to inject the database session into endpoints
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
