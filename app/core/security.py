import asyncio
from datetime import datetime, timedelta
from typing import Any, Union

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

# Security configuration for password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_access_token(
    subject: Union[str, Any], expires_delta: timedelta = None
) -> str:
    """
    Creates a JWT access token for a given user subject.
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Asynchronously verifies a plain password against a hash using a thread pool.
    """
    return await asyncio.to_thread(pwd_context.verify, plain_password, hashed_password)


async def get_password_hash(password: str) -> str:
    """
    Asynchronously hashes a password using a thread pool.
    """
    return await asyncio.to_thread(pwd_context.hash, password)
