import secrets
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, ApiKey
from app.schemas.apikey import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyOut
from app.api import deps
from app.core.rate_limit import limiter

router = APIRouter()
logger = logging.getLogger(__name__)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@router.post("", response_model=ApiKeyCreateResponse)
@limiter.limit("10/minute")
async def create_api_key(
    request: Request,
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    # Validate scopes
    allowed_scopes = {"chat:read", "chat:write", "documents:read", "documents:write", "admin:read", "admin:write"}
    for s in body.scopes:
        if s not in allowed_scopes:
            raise HTTPException(status_code=400, detail=f"Invalid scope: {s}")

    # Limit per user
    existing = await db.execute(select(ApiKey).where(ApiKey.user_id == current_user.id, ApiKey.is_active == True))  # noqa
    if len(existing.scalars().all()) >= 10:
        raise HTTPException(status_code=400, detail="API key limit (10) reached")

    raw = f"sk_{secrets.token_urlsafe(32)}"
    prefix = raw[:12]
    key_hash = _hash_key(raw)
    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)

    api_key = ApiKey(
        user_id=current_user.id,
        name=body.name,
        key_hash=key_hash,
        key_prefix=prefix,
        scopes=json.dumps(body.scopes),
        expires_at=expires_at,
    )
    db.add(api_key)
    try:
        await db.commit()
        await db.refresh(api_key)
    except Exception as e:
        await db.rollback()
        logger.error(f"API key create failed: {e}")
        raise HTTPException(status_code=500, detail="Could not create API key")

    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key=raw,
        key_prefix=prefix,
        scopes=body.scopes,
        expires_at=expires_at,
        created_at=api_key.created_at,
    )


@router.get("", response_model=list[ApiKeyOut])
@limiter.limit("30/minute")
async def list_api_keys(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    result = await db.execute(select(ApiKey).where(ApiKey.user_id == current_user.id).order_by(ApiKey.created_at.desc()))
    keys = result.scalars().all()
    out = []
    for k in keys:
        out.append(
            ApiKeyOut(
                id=k.id,
                name=k.name,
                key_prefix=k.key_prefix,
                scopes=json.loads(k.scopes or "[]"),
                is_active=k.is_active,
                expires_at=k.expires_at,
                last_used_at=k.last_used_at,
                created_at=k.created_at,
            )
        )
    return out


@router.delete("/{key_id}")
@limiter.limit("20/minute")
async def delete_api_key(
    request: Request,
    key_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id))
    api_key = result.scalars().first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    api_key.is_active = False
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Could not revoke key")
    return {"detail": "Revoked", "id": key_id}


@router.get("/{key_id}", response_model=ApiKeyOut)
@limiter.limit("30/minute")
async def get_api_key(
    request: Request,
    key_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id))
    api_key = result.scalars().first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    return ApiKeyOut(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        scopes=json.loads(api_key.scopes or "[]"),
        is_active=api_key.is_active,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
        created_at=api_key.created_at,
    )
