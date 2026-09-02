import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.db.models import User, UsageLedger
from app.api import deps
from app.core.rate_limit import limiter

router = APIRouter()


@router.get("/users")
@limiter.limit("30/minute")
async def list_users(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_superuser),
):
    result = await db.execute(select(User).order_by(User.id).limit(limit).offset(offset))
    users = result.scalars().all()
    # Return minimal info
    return [
        {
            "id": u.id,
            "email": u.email,
            "plan": getattr(u, "plan", "free"),
            "is_active": u.is_active,
            "is_superuser": getattr(u, "is_superuser", False),
            "created_at": getattr(u, "created_at", None),
        }
        for u in users
    ]


@router.get("/users/{user_id}/usage")
@limiter.limit("30/minute")
async def admin_user_usage(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_superuser),
):
    # total tokens + cost
    result = await db.execute(
        select(func.coalesce(func.sum(UsageLedger.total_tokens), 0), func.coalesce(func.sum(UsageLedger.cost_usd), 0.0)).where(
            UsageLedger.user_id == user_id
        )
    )
    tokens, cost = result.first() or (0, 0.0)
    return {"user_id": user_id, "total_tokens": int(tokens), "total_cost_usd": float(cost)}


@router.post("/users/{user_id}/ban")
@limiter.limit("10/minute")
async def ban_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_superuser),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    await db.commit()
    return {"detail": f"User {user_id} banned"}


@router.post("/users/{user_id}/unban")
@limiter.limit("10/minute")
async def unban_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_superuser),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    await db.commit()
    return {"detail": f"User {user_id} unbanned"}


@router.patch("/users/{user_id}/plan")
@limiter.limit("10/minute")
async def set_user_plan(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_superuser),
):
    body = await request.json()
    plan = body.get("plan")
    if plan not in ("free", "pro", "enterprise"):
        raise HTTPException(status_code=400, detail="Invalid plan")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.plan = plan
    await db.commit()
    return {"detail": f"User {user_id} plan -> {plan}", "plan": plan}


@router.get("/quotas")
@limiter.limit("30/minute")
async def list_quotas(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_superuser),
):
    # Simple aggregated quotas view
    from app.services.quota_service import get_plan_limit, get_monthly_usage
    result = await db.execute(select(User))
    users = result.scalars().all()
    out = []
    for u in users:
        limit = get_plan_limit(getattr(u, "plan", "free"))
        used = await get_monthly_usage(db, u.id)
        out.append({"user_id": u.id, "email": u.email, "plan": getattr(u, "plan", "free"), "limit": limit, "used": used, "remaining": max(0, limit - used)})
    return out
