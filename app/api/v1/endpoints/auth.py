from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core import security
from app.core.config import settings
from app.core.rate_limit import limiter
from app.api import deps
from app.db.models import User
from app.db.session import get_db
from app.schemas.user import UserCreate, UserOut
from app.schemas.token import Token

router = APIRouter()

# Pre-computed at import time so "user not found" and "wrong password" take the same time,
# preventing user-enumeration via timing side-channel.
_DUMMY_HASH: str = security.pwd_context.hash("__dummy_timing__")

@router.post("/login", response_model=Token)
@limiter.limit("3/minute")
async def login_access_token(
    request: Request,
    *,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalars().first()

    if not user:
        # Always run a dummy hash verification so "user not found" and "wrong password"
        # take the same time — prevents user-enumeration via timing side-channel.
        await security.verify_password(form_data.password, _DUMMY_HASH)
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    # Check lockout before password verification (handle both naive and aware datetimes)
    if user.locked_until:
        locked = user.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=timezone.utc)
        if locked > datetime.now(timezone.utc):
            raise HTTPException(
                status_code=423,
                detail=f"Account locked until {locked.isoformat()}. Try again later.",
            )

    if not await security.verify_password(form_data.password, user.hashed_password):
        # Increment failed attempts
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.LOCKOUT_MINUTES
            )
        try:
            await db.commit()
        except Exception:
            await db.rollback()
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    # Rehash if needed (migrate bcrypt -> argon2) and reset lockout
    updated = False
    if security.needs_rehash(user.hashed_password):
        user.hashed_password = await security.get_password_hash(form_data.password)
        updated = True
    if user.failed_login_attempts != 0 or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None
        updated = True
    if updated:
        try:
            await db.commit()
            await db.refresh(user)
        except Exception:
            await db.rollback()

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }

@router.post("/register", response_model=UserOut)
@limiter.limit("3/minute")
async def register_user(
    request: Request,
    *,
    db: AsyncSession = Depends(get_db),
    user_in: UserCreate,
) -> Any:
    """
    Create a new user in the system.
    """
    result = await db.execute(select(User).where(User.email == user_in.email))
    user = result.scalars().first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this username already exists in the system.",
        )
    
    db_obj = User(
        email=user_in.email,
        hashed_password=await security.get_password_hash(user_in.password),
        is_active=user_in.is_active,
    )
    db.add(db_obj)
    try:
        await db.commit()
        await db.refresh(db_obj)
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Could not create user.")
    return db_obj
