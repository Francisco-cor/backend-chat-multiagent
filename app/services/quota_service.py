"""Quota Service — Fase 9.3 Plan tiers + monthly token quota.

Tracks usage via UsageLedger (monthly window) and returns
remaining tokens + whether soft/hard limit hit.
"""
import calendar
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UsageLedger
from app.core.config import settings


PLAN_LIMITS = {
    "free": lambda: settings.QUOTA_FREE_TOKENS,
    "pro": lambda: settings.QUOTA_PRO_TOKENS,
    "enterprise": lambda: settings.QUOTA_ENTERPRISE_TOKENS,
}

def get_plan_limit(plan: str) -> int:
    fn = PLAN_LIMITS.get(plan or "free", PLAN_LIMITS["free"])
    return fn()


def _month_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day = calendar.monthrange(now.year, now.month)[1]
    end = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
    return start, end


async def get_monthly_usage(db: AsyncSession, user_id: int, now: datetime | None = None) -> int:
    start, end = _month_bounds(now)
    result = await db.execute(
        select(func.coalesce(func.sum(UsageLedger.total_tokens), 0)).where(
            UsageLedger.user_id == user_id,
            UsageLedger.created_at >= start,
            UsageLedger.created_at <= end,
        )
    )
    total = result.scalar() or 0
    return int(total)


async def check_quota(db: AsyncSession, user: User, tokens_needed: int = 0) -> dict:
    """Return dict {allowed, remaining, limit, used, soft_hit, hard_hit}."""
    limit = get_plan_limit(getattr(user, "plan", "free") or "free")
    used = await get_monthly_usage(db, user.id)
    remaining = max(0, limit - used)
    soft_threshold = int(limit * settings.QUOTA_SOFT_PCT)
    soft_hit = used >= soft_threshold
    hard_hit = used >= limit
    # If tokens_needed would exceed, deny
    allowed = (used + tokens_needed) <= limit
    return {
        "allowed": allowed or not hard_hit,  # if no tokens_needed specified, allow until hard
        "remaining": remaining,
        "limit": limit,
        "used": used,
        "soft_hit": soft_hit,
        "hard_hit": hard_hit,
    }


async def enforce_quota(db: AsyncSession, user: User, tokens_needed: int = 0):
    """Raise HTTP 429 if hard limit hit."""
    from fastapi import HTTPException

    info = await check_quota(db, user, tokens_needed)
    if info["hard_hit"] or (tokens_needed and not info["allowed"]):
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Quota exceeded",
                "plan": getattr(user, "plan", "free"),
                "limit": info["limit"],
                "used": info["used"],
                "remaining": info["remaining"],
            },
            headers={
                "X-Quota-Remaining": str(info["remaining"]),
                "X-Quota-Limit": str(info["limit"]),
                "Retry-After": "3600",
            },
        )
    return info
