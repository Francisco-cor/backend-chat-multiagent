from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Motor de base de datos asíncrono
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

# Fábrica de sesiones asíncronas
# Clave: expire_on_commit=False para evitar re-accesos perezosos tras commit (causa común del error xd2s)
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)

# Dependencia para inyectar la sesión en los endpoints
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
