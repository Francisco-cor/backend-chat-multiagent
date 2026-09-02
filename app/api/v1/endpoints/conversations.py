import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import get_db
from app.schemas.conversation import (
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    PaginatedConversations,
    PaginatedMessages,
)
from app.services.conversation_service import ConversationService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("", response_model=PaginatedConversations)
@limiter.limit("30/minute")
async def list_conversations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    cursor: int | None = Query(None, description="Last seen conversation id"),
):
    items, next_cursor = await ConversationService.list_conversations(
        db, current_user.id, limit=limit, cursor=cursor
    )
    return PaginatedConversations(items=items, next_cursor=next_cursor, has_more=next_cursor is not None)


@router.post("", response_model=ConversationOut, status_code=201)
@limiter.limit("10/minute")
async def create_conversation(
    request: Request,
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    conv = await ConversationService.get_or_create_conversation(
        db, current_user.id, payload.session_id, model=payload.model, title=payload.title
    )
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/{conversation_id}", response_model=ConversationOut)
@limiter.limit("30/minute")
async def get_conversation(
    request: Request,
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    conv = await ConversationService.get_conversation(db, current_user.id, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.get("/{conversation_id}/messages", response_model=PaginatedMessages)
@limiter.limit("30/minute")
async def get_conversation_messages(
    request: Request,
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    limit: int = Query(20, ge=1, le=100),
    cursor: int | None = Query(None, description="Last seen message id"),
):
    items, next_cursor = await ConversationService.get_messages(
        db, current_user.id, conversation_id, limit=limit, cursor=cursor
    )
    # Verify conversation exists for proper 404
    conv = await ConversationService.get_conversation(db, current_user.id, conversation_id)
    if not conv and not items:
        # Check if conversation exists but no messages, or truly not found
        # get_messages returns [] if conv not found, so we need to 404
        # Distinguish: if conv is None, then 404
        raise HTTPException(status_code=404, detail="Conversation not found")
    return PaginatedMessages(items=items, next_cursor=next_cursor, has_more=next_cursor is not None)


@router.patch("/{conversation_id}", response_model=ConversationOut)
@limiter.limit("20/minute")
async def update_conversation(
    request: Request,
    conversation_id: int,
    payload: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    conv = await ConversationService.update_title(db, current_user.id, conversation_id, payload.title)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.commit()
    await db.refresh(conv)
    return conv


@router.delete("/{conversation_id}")
@limiter.limit("10/minute")
async def delete_conversation(
    request: Request,
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    hard: bool = Query(False, description="Hard delete if true, soft otherwise"),
):
    if hard:
        ok = await ConversationService.hard_delete(db, current_user.id, conversation_id)
    else:
        ok = await ConversationService.soft_delete(db, current_user.id, conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.commit()
    return {"detail": "deleted", "hard": hard}


@router.post("/{conversation_id}/restore", response_model=ConversationOut)
@limiter.limit("10/minute")
async def restore_conversation(
    request: Request,
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    ok = await ConversationService.restore(db, current_user.id, conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found or not deleted")
    await db.commit()
    conv = await ConversationService.get_conversation(db, current_user.id, conversation_id)
    if not conv:
        # After restore, it should be found; but if hard deleted, not
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv
