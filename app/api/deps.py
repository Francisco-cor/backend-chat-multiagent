import hashlib
import json
from typing import Generator, Optional, Tuple

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core import security
from app.db.models import User, RevokedToken, ApiKey
from app.db.session import get_db
from app.schemas.token import TokenPayload

# OAuth2 documentation link
reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)
# Optional bearer for API-key alternative
api_key_header = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str = Depends(reusable_oauth2),
) -> User:
    """
    Retrieves the currently authenticated user from the JWT token.
    Validates jti blacklist, token type, and user existence.

    For backward compat, if token looks like an API key (sk_...), delegates
    to API-key path (so existing endpoints continue to work with api keys).
    Also supports X-API-Key header and query token for api keys.
    Sets request.state.principal_* for rate-limit / quota / billing.
    """
    # Try to extract token from multiple sources if OAuth2 didn't provide one
    raw = token
    if not raw:
        # Check Authorization header directly (covers X-API-Key alternative)
        auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            raw = auth[7:].strip()
        else:
            raw = request.headers.get("x-api-key") or request.headers.get("X-API-Key") or request.query_params.get("token") or ""
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    # API-key shortcut
    if raw.startswith("sk_"):
        user, api_key = await get_current_principal_via_api_key(raw, db)
        # stash for quota/billing
        try:
            request.state.principal_id = f"apikey:{api_key.id}"
            request.state.principal_type = "api_key"
            request.state.api_key = api_key
            request.state.api_key_scopes = json.loads(api_key.scopes or "[]")
            request.state.api_key_id = api_key.id
        except Exception:
            pass
        return user

    # Use raw for JWT decode (covers Bearer + X-API-Key fallback)
    jwt_token = raw if raw else token
    try:
        payload = jwt.decode(
            jwt_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (jwt.JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    # Enforce access token type
    if token_data.type and token_data.type != "access":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token type",
        )

    # Check revocation (jti blacklist)
    if token_data.jti:
        revoked = await db.execute(select(RevokedToken).where(RevokedToken.jti == token_data.jti))
        if revoked.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )

    try:
        user_id = int(token_data.sub)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    # stash principal for quota/rate-limit
    try:
        request.state.principal_id = f"user:{user.id}"
        request.state.principal_type = "user"
        request.state.api_key = None
        request.state.api_key_scopes = []
        request.state.api_key_id = None
    except Exception:
        pass
    return user


# ── API-Key principal helpers ──

def _hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_current_principal_via_api_key(raw_key: str, db: AsyncSession) -> Tuple[User, ApiKey]:
    """Validate raw API key and return (user, api_key). Updates last_used."""
    key_hash = _hash_api_key(raw_key)
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = result.scalars().first()
    if not api_key or not api_key.is_active:
        raise HTTPException(status_code=401, detail="Invalid API key")
    # expiry
    if api_key.expires_at:
        from datetime import datetime, timezone
        exp = api_key.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="API key expired")
    # fetch user
    res = await db.execute(select(User).where(User.id == api_key.user_id))
    user = res.scalars().first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive or not found")
    # update last_used (best-effort)
    try:
        from datetime import datetime, timezone
        api_key.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(api_key)
    except Exception:
        await db.rollback()
    return user, api_key


async def get_current_principal(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Tuple[User, Optional[ApiKey]]:
    """
    Returns (user, api_key_or_none).
    Accepts either:
     - Authorization: Bearer <jwt>
     - Authorization: Bearer sk_<api_key>
     - X-API-Key: sk_<api_key>
    Sets request.state.principal_id / principal_type for rate-limit keys.
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    x_api = request.headers.get("x-api-key") or request.headers.get("X-API-Key") or ""
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    elif x_api:
        token = x_api.strip()
    else:
        # fallback to OAuth2PasswordBearer extraction (query token param)
        token = request.query_params.get("token", "")

    if not token:
        raise HTTPException(status_code=401, detail="Missing credentials")

    # API key path
    if token.startswith("sk_"):
        user, api_key = await get_current_principal_via_api_key(token, db)
        request.state.principal_id = f"apikey:{api_key.id}"
        request.state.principal_type = "api_key"
        request.state.api_key = api_key
        request.state.api_key_scopes = json.loads(api_key.scopes or "[]")
        return user, api_key

    # JWT path
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = TokenPayload(**payload)
    except (jwt.JWTError, ValidationError):
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    if token_data.type and token_data.type != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    if token_data.jti:
        revoked = await db.execute(select(RevokedToken).where(RevokedToken.jti == token_data.jti))
        if revoked.scalars().first():
            raise HTTPException(status_code=401, detail="Token revoked")
    try:
        user_id = int(token_data.sub)  # type: ignore
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    request.state.principal_id = f"user:{user.id}"
    request.state.principal_type = "user"
    request.state.api_key_scopes = []
    return user, None


def require_scopes(required: list[str]):
    """Dependency factory to enforce API-key scopes (JWT bypasses scope check)."""

    async def _check(request: Request, principal: Tuple[User, Optional[ApiKey]] = Depends(get_current_principal)):
        user, api_key = principal
        if api_key is None:
            # JWT — allow all (or optionally check user roles)
            return user
        scopes = json.loads(api_key.scopes or "[]")
        for s in required:
            if s not in scopes:
                raise HTTPException(status_code=403, detail=f"Missing scope: {s}")
        return user

    return _check


async def get_current_superuser(
    principal: Tuple[User, Optional[ApiKey]] = Depends(get_current_principal),
) -> User:
    user, _ = principal
    if not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Superuser required")
    return user
