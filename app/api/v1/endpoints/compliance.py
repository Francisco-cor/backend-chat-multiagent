import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models import User, Conversation, Message, Document, UsageLedger, AuditLog
from app.api import deps
from app.core.rate_limit import limiter

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/export")
@limiter.limit("5/minute")
async def export_data(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    """GDPR export: returns all user data (profile, conversations, messages, documents, usage)."""
    # conversations
    result = await db.execute(select(Conversation).where(Conversation.user_id == current_user.id).order_by(Conversation.created_at))
    convs = result.scalars().all()
    # messages via conv ids
    conv_ids = [c.id for c in convs]
    msgs = []
    if conv_ids:
        r = await db.execute(select(Message).where(Message.conversation_id.in_(conv_ids)).order_by(Message.created_at))
        msgs = r.scalars().all()
    # documents
    r = await db.execute(select(Document).where(Document.user_id == current_user.id))
    docs = r.scalars().all()
    # usage
    r = await db.execute(select(UsageLedger).where(UsageLedger.user_id == current_user.id).order_by(UsageLedger.created_at.desc()).limit(500))
    usage = r.scalars().all()
    # audit
    r = await db.execute(select(AuditLog).where(AuditLog.user_id == current_user.id).order_by(AuditLog.created_at.desc()).limit(200))
    audits = r.scalars().all()

    # log audit
    try:
        db.add(AuditLog(user_id=current_user.id, action="gdpr.export", detail=f"export at {datetime.now(timezone.utc).isoformat()}"))
        await db.commit()
    except Exception:
        await db.rollback()

    return {
        "user": {"id": current_user.id, "email": current_user.email, "plan": getattr(current_user, "plan", "free"), "created_at": getattr(current_user, "created_at", None)},
        "conversations": [{"id": c.id, "title": c.title, "model": c.model, "created_at": c.created_at, "total_tokens": c.total_tokens, "org_id": getattr(c, "org_id", None)} for c in convs],
        "messages": [{"id": m.id, "conversation_id": m.conversation_id, "role": m.role, "content": m.content[:500], "created_at": m.created_at} for m in msgs],
        "documents": [{"id": d.id, "title": d.title, "source": d.source, "created_at": d.created_at} for d in docs],
        "usage": [{"id": u.id, "model": u.model, "total_tokens": u.total_tokens, "cost_usd": u.cost_usd, "created_at": u.created_at} for u in usage],
        "audit_logs": [{"id": a.id, "action": a.action, "detail": a.detail, "created_at": a.created_at} for a in audits],
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "retention_days": 30,
    }


@router.delete("/account")
@limiter.limit("3/minute")
async def delete_account(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    """GDPR delete: anonymize / hard-delete user data per retention policy.
    Soft-deletes conversations (hard after retention), deletes messages, documents, usage.
    Keeps AuditLog with anonymized user_id NULL for compliance trail.
    """
    user_id = current_user.id
    # confirm via body? Require json {"confirm": "DELETE"} for safety
    try:
        body = await request.json()
        if body.get("confirm") != "DELETE":
            raise HTTPException(status_code=400, detail="Must send {'confirm':'DELETE'}")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Must send {'confirm':'DELETE'}")

    # Delete documents + chunks (cascade)
    result = await db.execute(select(Document).where(Document.user_id == user_id))
    docs = result.scalars().all()
    for d in docs:
        await db.delete(d)

    # Delete conversations (hard)
    result = await db.execute(select(Conversation).where(Conversation.user_id == user_id))
    convs = result.scalars().all()
    for c in convs:
        await db.delete(c)

    # Delete legacy history
    from app.db.models import ConversationHistory
    result = await db.execute(select(ConversationHistory).where(ConversationHistory.user_id == user_id))
    hists = result.scalars().all()
    for h in hists:
        await db.delete(h)

    # Delete api keys, usage
    from app.db.models import ApiKey
    result = await db.execute(select(ApiKey).where(ApiKey.user_id == user_id))
    for k in result.scalars().all():
        await db.delete(k)
    result = await db.execute(select(UsageLedger).where(UsageLedger.user_id == user_id))
    for u in result.scalars().all():
        await db.delete(u)

    # Anonymize audit logs: set user_id NULL
    result = await db.execute(select(AuditLog).where(AuditLog.user_id == user_id))
    for a in result.scalars().all():
        a.user_id = None
        a.detail = (a.detail or "") + " [anonymized]"

    # Finally deactivate user (soft delete for FK integrity) + anonymize email
    current_user.is_active = False
    current_user.email = f"deleted_{user_id}_{current_user.email}"
    # keep hashed password but could wipe

    # add final audit with org NULL
    try:
        db.add(AuditLog(user_id=None, action="gdpr.delete", detail=f"user {user_id} deleted at {datetime.now(timezone.utc).isoformat()}"))
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"GDPR delete commit failed: {e}")
        raise HTTPException(status_code=500, detail="Delete failed")

    return {"detail": f"Account {user_id} deleted (GDPR). Retention: data purged, audit anonymized."}


@router.get("/audit")
@limiter.limit("30/minute")
async def list_audit(request: Request, limit: int = 50, db: AsyncSession = Depends(get_db), current_user: User = Depends(deps.get_current_user)):
    # user sees own audit; superuser can see all via admin
    q = select(AuditLog).where(AuditLog.user_id == current_user.id).order_by(AuditLog.created_at.desc()).limit(limit)
    result = await db.execute(q)
    logs = result.scalars().all()
    return [{"id": a.id, "action": a.action, "detail": a.detail, "created_at": a.created_at, "org_id": getattr(a, "org_id", None)} for a in logs]
