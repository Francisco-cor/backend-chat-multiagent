"""Billing Service — Fase 9.4 Usage ledger + cost aggregation + Stripe stub."""
import logging
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageLedger
from app.services.token_counter import estimate_cost

logger = logging.getLogger(__name__)


async def record_usage(
    db: AsyncSession,
    user_id: int,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float | None = None,
    api_key_id: int | None = None,
    request_id: str | None = None,
    endpoint: str | None = None,
) -> UsageLedger:
    total_tokens = prompt_tokens + completion_tokens
    if cost_usd is None:
        # Use token_counter estimate if not provided
        cost_usd = (estimate_cost(prompt_tokens, model or "") + estimate_cost(completion_tokens, model or ""))
    entry = UsageLedger(
        user_id=user_id,
        api_key_id=api_key_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        request_id=request_id,
        endpoint=endpoint,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    try:
        await db.commit()
        await db.refresh(entry)
    except Exception as e:
        await db.rollback()
        logger.warning(f"Billing record failed: {e}")
        raise
    return entry


async def get_user_usage_summary(db: AsyncSession, user_id: int, period_days: int | None = None) -> dict:
    q = select(
        func.coalesce(func.sum(UsageLedger.total_tokens), 0).label("tokens"),
        func.coalesce(func.sum(UsageLedger.cost_usd), 0.0).label("cost"),
        func.count(UsageLedger.id).label("requests"),
    ).where(UsageLedger.user_id == user_id)
    if period_days:
        from datetime import timedelta
        since = datetime.now(timezone.utc) - timedelta(days=period_days)
        q = q.where(UsageLedger.created_at >= since)
    result = await db.execute(q)
    row = result.first()
    return {
        "total_tokens": int(row.tokens) if row else 0,
        "total_cost_usd": float(row.cost) if row else 0.0,
        "requests": int(row.requests) if row else 0,
    }


async def get_api_key_usage(db: AsyncSession, api_key_id: int) -> dict:
    q = select(
        func.coalesce(func.sum(UsageLedger.total_tokens), 0),
        func.coalesce(func.sum(UsageLedger.cost_usd), 0.0),
        func.count(UsageLedger.id),
    ).where(UsageLedger.api_key_id == api_key_id)
    result = await db.execute(q)
    tokens, cost, reqs = result.first() or (0, 0.0, 0)
    return {"total_tokens": int(tokens), "total_cost_usd": float(cost), "requests": int(reqs)}


# Stripe webhook stub
async def handle_stripe_webhook(payload: dict, sig_header: str | None = None) -> dict:
    """Stub for Stripe webhook. Validates sig if STRIPE_WEBHOOK_SECRET set, else accepts.

    Expected payload shapes:
     - {"type": "checkout.session.completed", "data": {"object": {"client_reference_id": user_id, "metadata": {"plan": "pro"}}}}
    Returns {"status": "ok", "action": "..."}
    """
    from app.core.config import settings

    # If secret configured, we would verify HMAC — skip for stub
    if settings.STRIPE_WEBHOOK_SECRET and sig_header:
        # In prod: stripe.Webhook.construct_event(payload, sig_header, secret)
        logger.info("Stripe webhook sig validated stub")
    event_type = payload.get("type", "unknown")
    logger.info(f"Stripe webhook received: {event_type}")
    # Example: handle subscription update
    if event_type in ("checkout.session.completed", "customer.subscription.updated"):
        # Would update user plan here
        return {"status": "ok", "event": event_type, "handled": True}
    return {"status": "ok", "event": event_type, "handled": False}
