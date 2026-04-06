import logging
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, asc
from app.db.models import ConversationHistory
from app.services.llm_providers import GoogleGeminiProvider, OpenAIProvider, ClaudeProvider, LLMProvider
from app.core.config import settings
from fastapi import HTTPException
from openai import APIConnectionError, RateLimitError
import anthropic

logger = logging.getLogger(__name__)

# DB Helpers
async def get_history(session_id: str, db: AsyncSession, user_id: int, limit: int = settings.HISTORY_LIMIT):
    """
    Returns the most recent `limit` messages for the given user+session in
    chronological (asc) order. Filters by user_id to enforce data isolation.
    """
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
) -> None:
    """
    Saves both the user message and model reply in a single atomic commit.
    If the commit fails both rows are rolled back together.
    """
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
    async def process_chat(
        session_id: str,
        prompt: str,
        model_name: str,
        db: AsyncSession,
        user_id: int,
        openai_client=None,
        image_data: Optional[dict] = None,
        file_data: Optional[dict] = None,
        use_search: bool = False
    ) -> str:
        """
        Orchestrates the chat process: fetches history, generates reply from LLM,
        and atomically saves user message + model response.
        """
        logger.info(f"Processing: Sess={session_id} | Mod={model_name} | Search={use_search}")

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
                await save_exchange(session_id, prompt, reply, db, user_id=user_id)
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
        image_data: Optional[dict] = None,
        file_data: Optional[dict] = None,
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

        full_reply: List[str] = []
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
                    await save_exchange(session_id, prompt, reply_text, db, user_id=user_id)
                except Exception:
                    logger.error(f"Failed to persist streamed reply for session {session_id}")
