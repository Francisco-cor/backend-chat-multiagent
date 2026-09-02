from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, asc, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message
from app.services.token_counter import count_message_tokens, estimate_cost


class ConversationService:
    @staticmethod
    async def get_or_create_conversation(
        db: AsyncSession,
        user_id: int,
        session_id: str,
        model: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Conversation:
        # Try to find existing conversation by legacy_session_id + user_id and not deleted
        result = await db.execute(
            select(Conversation).where(
                Conversation.user_id == user_id,
                Conversation.legacy_session_id == session_id,
                Conversation.deleted_at.is_(None),
            )
        )
        conv = result.scalars().first()
        if conv:
            # Update updated_at and model if provided
            if model and conv.model != model:
                conv.model = model
            conv.updated_at = datetime.now(timezone.utc)
            await db.flush()
            return conv

        # Create new
        conv = Conversation(
            user_id=user_id,
            legacy_session_id=session_id,
            title=title or f"Chat {session_id[:20]}",
            model=model,
            total_tokens=0,
            total_cost_usd=0.0,
        )
        db.add(conv)
        await db.flush()
        await db.refresh(conv)
        return conv

    @staticmethod
    async def get_conversation(
        db: AsyncSession, user_id: int, conversation_id: int
    ) -> Optional[Conversation]:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    @staticmethod
    async def list_conversations(
        db: AsyncSession,
        user_id: int,
        limit: int = 20,
        cursor: Optional[int] = None,
        include_deleted: bool = False,
    ) -> Tuple[List[Conversation], Optional[int]]:
        # Cursor-based pagination: cursor is last seen id, fetch next page ordered by updated_at desc, id desc
        query = select(Conversation).where(Conversation.user_id == user_id)
        if not include_deleted:
            query = query.where(Conversation.deleted_at.is_(None))
        if cursor is not None:
            # Get cursor conversation to know its updated_at
            cur_result = await db.execute(select(Conversation).where(Conversation.id == cursor))
            cur_conv = cur_result.scalars().first()
            if cur_conv:
                # Fetch next page where (updated_at < cur.updated_at) OR (updated_at == cur.updated_at AND id < cur.id)
                query = query.where(
                    (Conversation.updated_at < cur_conv.updated_at)
                    | ((Conversation.updated_at == cur_conv.updated_at) & (Conversation.id < cur_conv.id))
                )
        query = query.order_by(desc(Conversation.updated_at), desc(Conversation.id)).limit(limit + 1)
        result = await db.execute(query)
        items = list(result.scalars().all())
        next_cursor = None
        if len(items) > limit:
            next_cursor = items[-1].id
            items = items[:limit]
        elif items:
            # If exactly limit, next_cursor is last id if there may be more, else None via extra fetch
            # We used limit+1, so if len == limit+1 we already handled, if len == limit but there could be more we need to know
            # Our limit+1 handles this: if we got limit+1, we popped, else no next
            pass
        return items, next_cursor

    @staticmethod
    async def get_messages(
        db: AsyncSession,
        user_id: int,
        conversation_id: int,
        limit: int = 20,
        cursor: Optional[int] = None,
    ) -> Tuple[List[Message], Optional[int]]:
        # Verify ownership
        conv = await ConversationService.get_conversation(db, user_id, conversation_id)
        if not conv:
            return [], None
        # Ascending cursor pagination: cursor is last seen id, fetch next page
        query = select(Message).where(Message.conversation_id == conversation_id)
        if cursor is not None:
            query = query.where(Message.id > cursor)
        query = query.order_by(asc(Message.id)).limit(limit + 1)
        result = await db.execute(query)
        items = list(result.scalars().all())
        next_cursor = None
        if len(items) > limit:
            next_cursor = items[limit - 1].id
            items = items[:limit]
        return items, next_cursor

    @staticmethod
    async def get_history(
        db: AsyncSession, user_id: int, conversation_id: int, limit: int = 15
    ) -> List[Message]:
        # Get most recent limit messages in asc order
        conv = await ConversationService.get_conversation(db, user_id, conversation_id)
        if not conv:
            return []
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at), desc(Message.id))
            .limit(limit)
        )
        items = list(reversed(result.scalars().all()))
        return items

    @staticmethod
    async def save_exchange(
        db: AsyncSession,
        conversation_id: int,
        user_id: int,
        user_msg: str,
        model_reply: str,
        model: Optional[str] = None,
    ) -> Tuple[Message, Message]:
        conv = await ConversationService.get_conversation(db, user_id, conversation_id)
        if not conv:
            raise ValueError("Conversation not found")

        tokens_user = count_message_tokens(user_msg, "user")
        tokens_model = count_message_tokens(model_reply, "model")
        cost_user = estimate_cost(tokens_user, model or conv.model or "")
        cost_model = estimate_cost(tokens_model, model or conv.model or "")

        user_message = Message(
            conversation_id=conversation_id,
            role="user",
            content=user_msg,
            tokens=tokens_user,
            cost_usd=cost_user,
            legacy_session_id=conv.legacy_session_id,
        )
        model_message = Message(
            conversation_id=conversation_id,
            role="model",
            content=model_reply,
            tokens=tokens_model,
            cost_usd=cost_model,
            legacy_session_id=conv.legacy_session_id,
        )
        db.add(user_message)
        db.add(model_message)

        # Update conversation totals
        conv.total_tokens = (conv.total_tokens or 0) + tokens_user + tokens_model
        conv.total_cost_usd = (conv.total_cost_usd or 0.0) + cost_user + cost_model
        conv.updated_at = datetime.now(timezone.utc)
        if model:
            conv.model = model
        # Auto-generate title from first user message if still default
        if conv.title and conv.title.startswith("Chat ") and len(conv.title) < 30:
            # Use first 50 chars of first message as title if not set meaningfully
            snippet = user_msg[:50].strip()
            if snippet:
                conv.title = snippet

        await db.flush()
        await db.refresh(user_message)
        await db.refresh(model_message)
        await db.refresh(conv)
        return user_message, model_message

    @staticmethod
    async def update_title(
        db: AsyncSession, user_id: int, conversation_id: int, title: str
    ) -> Optional[Conversation]:
        conv = await ConversationService.get_conversation(db, user_id, conversation_id)
        if not conv:
            return None
        conv.title = title[:255]
        conv.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(conv)
        return conv

    @staticmethod
    async def soft_delete(
        db: AsyncSession, user_id: int, conversation_id: int
    ) -> bool:
        conv = await ConversationService.get_conversation(db, user_id, conversation_id)
        if not conv:
            return False
        conv.deleted_at = datetime.now(timezone.utc)
        await db.flush()
        return True

    @staticmethod
    async def restore(
        db: AsyncSession, user_id: int, conversation_id: int
    ) -> bool:
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        conv = result.scalars().first()
        if not conv or conv.deleted_at is None:
            return False
        conv.deleted_at = None
        conv.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return True

    @staticmethod
    async def hard_delete(
        db: AsyncSession, user_id: int, conversation_id: int
    ) -> bool:
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        conv = result.scalars().first()
        if not conv:
            return False
        await db.delete(conv)
        await db.flush()
        return True
