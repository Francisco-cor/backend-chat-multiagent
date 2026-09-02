import logging
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, UsageLedger
from app.schemas.billing import UsageOut, UsageSummary
from app.api import deps
from app.core.rate_limit import limiter
from app.services.billing_service import get_user_usage_summary, handle_stripe_webhook

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/usage", response_model=UsageSummary)
@limiter.limit("30/minute")
async def get_usage(
    request: Request,
    period_days: int | None = Query(None, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    summary = await get_user_usage_summary(db, current_user.id, period_days=period_days)
    summary["period_days"] = period_days
    return summary


@router.get("/ledger", response_model=list[UsageOut])
@limiter.limit("30/minute")
async def list_ledger(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    result = await db.execute(
        select(UsageLedger)
        .where(UsageLedger.user_id == current_user.id)
        .order_by(UsageLedger.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    return rows


@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # Read raw body
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    sig = request.headers.get("stripe-signature")
    result = await handle_stripe_webhook(payload, sig_header=sig)
    # If payload contains plan update, we stub apply
    try:
        data_obj = payload.get("data", {}).get("object", {})
        client_ref = data_obj.get("client_reference_id")
        metadata = data_obj.get("metadata", {})
        plan = metadata.get("plan")
        if client_ref and plan and result.get("handled"):
            # client_ref is user_id str
            from sqlalchemy import select
            from app.db.models import User

            uid = int(client_ref)
            res = await db.execute(select(User).where(User.id == uid))
            user = res.scalars().first()
            if user:
                if plan in ("free", "pro", "enterprise"):
                    user.plan = plan
                    await db.commit()
                    logger.info(f"Stripe: user {uid} plan -> {plan}")
    except Exception as e:
        logger.warning(f"Stripe webhook plan update failed: {e}")
    return result
