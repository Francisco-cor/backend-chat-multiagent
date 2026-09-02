import asyncio
import uuid
from typing import Any, Union
from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

# Security configuration for password hashing
# Dual-scheme: new hashes use argon2, old bcrypt hashes remain verifiable.
# This fixes the bcrypt 4.0.1 + passlib incompatibility and removes 72-byte limit.
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")


def create_access_token(
    subject: Union[str, Any], expires_delta: timedelta | None = None
) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "exp": expire,
        "iat": now,
        "sub": str(subject),
        "jti": str(uuid.uuid4()),
        "type": "access",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    subject: Union[str, Any], expires_delta: timedelta | None = None
) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "exp": expire,
        "iat": now,
        "sub": str(subject),
        "jti": str(uuid.uuid4()),
        "type": "refresh",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def needs_rehash(hashed_password: str) -> bool:
    """Check if hash needs migration to argon2."""
    return pwd_context.needs_update(hashed_password)


async def get_password_hash(password: str) -> str:
    # Use to_thread because hashing is CPU-intensive and synchronous
    return await asyncio.to_thread(pwd_context.hash, password)


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Also use to_thread for verification to avoid blocking the event loop
    return await asyncio.to_thread(pwd_context.verify, plain_password, hashed_password)
