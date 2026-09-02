import logging

import anthropic
from fastapi import HTTPException
from openai import APIConnectionError, RateLimitError
from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import ConversationHistory
from app.services.conversation_service import ConversationService
from app.services.llm_providers import (
    ClaudeProvider,
    GoogleGeminiProvider,
    LLMProvider,
    OpenAIProvider,
)

logger = logging.getLogger(__name__)

# Legacy DB Helpers (kept for backward compat, now delegate to ConversationService)
async def get_history(session_id: str, db: AsyncSession, user_id: int, limit: int = settings.HISTORY_LIMIT):
    """
    Returns the most recent `limit` messages for the given user+session in
    chronological (asc) order. Filters by user_id to enforce data isolation.
    Delegates to ConversationService (new) with fallback to legacy table.
    """
    # Try ConversationService (new schema)
    try:
        from app.db.models import Conversation

        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.user_id == user_id,
                Conversation.legacy_session_id == session_id,
                Conversation.deleted_at.is_(None),
            )
        )
        conv = conv_result.scalars().first()
        if conv:
            msgs = await ConversationService.get_history(db, user_id, conv.id, limit=limit)
            if msgs:
                return msgs
    except Exception:
        pass

    # Fallback legacy
    newest_ids = (
        select(ConversationHistory.id)
        .where(
            ConversationHistory.session_id == session_id,
            ConversationHistory.user_id == user_id,
        )
        .order_by(ConversationHistory.timestamp.desc())
        .limit(limit)
        .scalar_subquery()
    )
    result = await db.execute(
        select(ConversationHistory)
        .where(ConversationHistory.id.in_(newest_ids))
        .order_by(asc(ConversationHistory.timestamp))
    )
    return result.scalars().all()


async def save_exchange(
    session_id: str,
    user_msg: str,
    model_reply: str,
    db: AsyncSession,
    user_id: int,
    model: str | None = None,
) -> None:
    """
    Saves both the user message and model reply.
    Writes to new Conversation/Message and legacy ConversationHistory for transition.
    """
    # Try new schema
    try:
        from app.db.models import Conversation

        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.user_id == user_id,
                Conversation.legacy_session_id == session_id,
                Conversation.deleted_at.is_(None),
            )
        )
        conv = conv_result.scalars().first()
        if not conv:
            conv = await ConversationService.get_or_create_conversation(
                db, user_id, session_id, model=model, title=user_msg[:50]
            )
        await ConversationService.save_exchange(db, conv.id, user_id, user_msg, model_reply, model=model)
        await db.commit()
        # Also write legacy for back-compat (best-effort)
        try:
            user_record = ConversationHistory(
                session_id=session_id, role="user", content=user_msg, user_id=user_id
            )
            model_record = ConversationHistory(
                session_id=session_id, role="model", content=model_reply, user_id=user_id
            )
            db.add(user_record)
            db.add(model_record)
            await db.commit()
        except Exception:
            await db.rollback()
        return
    except Exception as e:
        logger.warning(f"New schema save failed, fallback to legacy: {e}")
        await db.rollback()

    # Fallback legacy
    user_record = ConversationHistory(
        session_id=session_id, role="user", content=user_msg, user_id=user_id
    )
    model_record = ConversationHistory(
        session_id=session_id, role="model", content=model_reply, user_id=user_id
    )
    db.add(user_record)
    db.add(model_record)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise


class ChatService:
    @staticmethod
    def get_provider(model_name: str, openai_client=None) -> LLMProvider:
        """
        Factory method to return the appropriate LLM provider based on model name.
        """
        model_lower = model_name.lower()

        if "gemini" in model_lower:
            return GoogleGeminiProvider(model_name=model_name, api_key=settings.GOOGLE_API_KEY)

        elif "gpt" in model_lower:
            return OpenAIProvider(model_name=model_name, client=openai_client)

        elif "claude" in model_lower:
            if not settings.ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY is not configured.")
            return ClaudeProvider(model_name=model_name, api_key=settings.ANTHROPIC_API_KEY)

        raise ValueError(f"Model not supported: {model_name}")

    @staticmethod
    async def process_chat_orchestrated(
        session_id: str,
        prompt: str,
        model_name: str,
        db: AsyncSession,
        user_id: int,
        openai_client=None,
        image_data: dict | None = None,
        file_data: dict | None = None,
        use_search: bool = False,
        strategy: str = "auto",
    ) -> tuple[str, list]:
        """
        Orchestrated multi-agent chat. Returns (reply, trace).
        """
        logger.info(f"Orchestrated: Sess={session_id} | Strat={strategy} | Prompt={prompt[:80]}")
        history = await get_history(session_id, db, user_id=user_id)
        try:
            # Lazy import to avoid circular
            from app.agents.orchestrator import SupervisorOrchestrator

            orchestrator = SupervisorOrchestrator()
            context = {
                "openai_client": openai_client,
                "image_data": image_data,
                "file_data": file_data,
                "model_name": model_name,
                "use_search": use_search,
            }
            reply, trace = await orchestrator.orchestrate(
                prompt, history, context=context, strategy=strategy
            )
            try:
                await save_exchange(session_id, prompt, reply, db, user_id=user_id, model=model_name)
            except Exception:
                logger.error(f"Failed to persist orchestrated exchange {session_id}")
            return reply, trace
        except Exception as e:
            logger.exception(f"Orchestrator failed, falling back to direct: {e}")
            # Fallback to direct
            reply = await ChatService.process_chat(
                session_id, prompt, model_name, db, user_id, openai_client, image_data, file_data, use_search
            )
            return reply, [{"agent": "fallback", "output": reply}]

    @staticmethod
    async def process_chat(
        session_id: str,
        prompt: str,
        model_name: str,
        db: AsyncSession,
        user_id: int,
        openai_client=None,
        image_data: dict | None = None,
        file_data: dict | None = None,
        use_search: bool = False
    ) -> str:
        """
        Orchestrates the chat process: fetches history, generates reply from LLM,
        and atomically saves user message + model response.
        If orchestrator is enabled and prompt triggers multi-agent, delegates.
        """
        logger.info(f"Processing: Sess={session_id} | Mod={model_name} | Search={use_search}")

        # Auto-route to orchestrator if enabled and prompt suggests multi-agent
        if settings.ORCHESTRATOR_ENABLED and any(
            k in prompt.lower() for k in ["investiga", "analiza", "orchestrate", "research", "critic"]
        ):
            try:
                reply, _ = await ChatService.process_chat_orchestrated(
                    session_id, prompt, model_name, db, user_id, openai_client, image_data, file_data, use_search, strategy=settings.ORCHESTRATOR_STRATEGY
                )
                return reply
            except Exception:
                logger.warning("Orchestrator auto-route failed, using direct")

        history = await get_history(session_id, db, user_id=user_id)

        try:
            provider = ChatService.get_provider(model_name, openai_client)

            reply = await provider.generate(
                prompt=prompt,
                history=history,
                image_data=image_data,
                file_data=file_data,
                use_search=use_search
            )

            # Save both messages atomically after a successful LLM response.
            try:
                await save_exchange(session_id, prompt, reply, db, user_id=user_id, model=model_name)
            except Exception:
                logger.error(f"Failed to persist exchange for session {session_id}")
                # The client still receives the reply even if persistence fails.

            return reply

        except (RateLimitError, anthropic.RateLimitError):
            logger.warning(f"Rate limit hit in LLM provider (Sess={session_id})")
            raise HTTPException(status_code=429, detail="LLM Rate Limit Exceeded. Please try again later.")

        except (APIConnectionError, anthropic.APIConnectionError):
            logger.error(f"Connection error with LLM (Sess={session_id})")
            raise HTTPException(status_code=503, detail="LLM Provider Unavailable.")

        except RuntimeError as e:
            if "timed out" in str(e).lower():
                logger.warning(f"LLM request timed out (Sess={session_id})")
                raise HTTPException(status_code=503, detail="LLM request timed out.")
            logger.exception(f"Critical error in LLM: {e}")
            raise HTTPException(status_code=500, detail="Internal Error processing chat.")

        except Exception as e:
            logger.exception(f"Critical error in LLM: {e}")
            raise HTTPException(status_code=500, detail="Internal Error processing chat.")

    @staticmethod
    async def process_chat_stream(
        session_id: str,
        prompt: str,
        model_name: str,
        db: AsyncSession,
        user_id: int,
        openai_client=None,
        image_data: dict | None = None,
        file_data: dict | None = None,
        use_search: bool = False,
    ):
        """
        Async generator that streams LLM response chunks.
        Persists user + model messages to DB atomically after the stream completes.
        """
        logger.info(f"Streaming: Sess={session_id} | Mod={model_name}")

        history = await get_history(session_id, db, user_id=user_id)

        try:
            provider = ChatService.get_provider(model_name, openai_client)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        full_reply: list[str] = []
        try:
            async for chunk in provider.generate_stream(
                prompt=prompt,
                history=history,
                image_data=image_data,
                file_data=file_data,
                use_search=use_search,
            ):
                full_reply.append(chunk)
                yield chunk

        except (RateLimitError, anthropic.RateLimitError):
            logger.warning(f"Rate limit hit in stream (Sess={session_id})")
            raise HTTPException(status_code=429, detail="LLM Rate Limit Exceeded.")
        except (APIConnectionError, anthropic.APIConnectionError):
            logger.error(f"Connection error in stream (Sess={session_id})")
            raise HTTPException(status_code=503, detail="LLM Provider Unavailable.")
        except Exception as e:
            logger.exception(f"Stream error: {e}")
            raise HTTPException(status_code=500, detail="Internal Error processing stream.")
        finally:
            if full_reply:
                reply_text = "".join(full_reply)
                try:
                    await save_exchange(session_id, prompt, reply_text, db, user_id=user_id, model=model_name)
                except Exception:
                    logger.error(f"Failed to persist streamed reply for session {session_id}")

    @staticmethod
    async def process_chat_stream_orchestrated(
        session_id: str,
        prompt: str,
        model_name: str,
        db: AsyncSession,
        user_id: int,
        openai_client=None,
        image_data: dict | None = None,
        file_data: dict | None = None,
        use_search: bool = False,
        strategy: str = "auto",
    ):
        """
        Orchestrated streaming via SupervisorOrchestrator.
        Yields dict events {agent, event, delta}.
        """
        logger.info(f"Orchestrated stream: Sess={session_id} | Strat={strategy}")
        history = await get_history(session_id, db, user_id=user_id)
        full_reply: list[str] = []
        try:
            from app.agents.orchestrator import SupervisorOrchestrator

            orchestrator = SupervisorOrchestrator()
            context = {
                "openai_client": openai_client,
                "image_data": image_data,
                "file_data": file_data,
                "model_name": model_name,
                "use_search": use_search,
            }
            async for event in orchestrator.orchestrate_stream(
                prompt, history, context=context, strategy=strategy
            ):
                if event.get("event") == "delta" and event.get("delta"):
                    full_reply.append(event["delta"])
                yield event
            # Persist after successful stream
            if full_reply:
                try:
                    await save_exchange(
                        session_id, prompt, "".join(full_reply), db, user_id=user_id, model=model_name
                    )
                except Exception:
                    logger.error(f"Failed to persist orchestrated stream {session_id}")
        except Exception as e:
            logger.exception(f"Orchestrated stream failed: {e}")
            # Fallback to direct stream
            fallback_reply: list[str] = []
            async for chunk in ChatService.process_chat_stream(
                session_id, prompt, model_name, db, user_id, openai_client, image_data, file_data, use_search
            ):
                fallback_reply.append(chunk)
                yield {"agent": "fallback", "event": "delta", "delta": chunk}
            yield {"agent": "fallback", "event": "done", "delta": ""}
            if fallback_reply:
                try:
                    await save_exchange(
                        session_id, prompt, "".join(fallback_reply), db, user_id=user_id, model=model_name
                    )
                except Exception:
                    logger.error(f"Failed to persist fallback stream {session_id}")
