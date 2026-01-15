import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import ConversationHistory
from app.services.llm_providers import GoogleGeminiProvider, OpenAIProvider, LLMProvider
from app.core.config import settings
from fastapi import HTTPException
from openai import APIConnectionError, RateLimitError

logger = logging.getLogger(__name__)

# Helpers de DB
async def get_history(session_id: str, db: AsyncSession, limit: int = 15):
    # Redujimos limit a 15 para dar espacio a contextos largos de Gemini 3
    result = await db.execute(
        select(ConversationHistory)
        .where(ConversationHistory.session_id == session_id)
        .order_by(ConversationHistory.timestamp.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))

async def save_message(session_id: str, role: str, content: str, db: AsyncSession):
    msg = ConversationHistory(session_id=session_id, role=role, content=content)
    db.add(msg)
    await db.commit()

class ChatService:
    @staticmethod
    def get_provider(model_name: str, openai_client=None) -> LLMProvider:
        model_lower = model_name.lower()
        
        if "gemini" in model_lower:
            # Aquí entran gemini-2.5-pro, gemini-3.0-pro-preview, etc.
            return GoogleGeminiProvider(model_name=model_name, api_key=settings.GOOGLE_API_KEY)
        
        elif "gpt" in model_lower:
            return OpenAIProvider(model_name=model_name, client=openai_client)
        
        raise ValueError(f"Modelo no soportado: {model_name}")

    @staticmethod
    async def process_chat(
        session_id: str,
        prompt: str,
        model_name: str,
        db: AsyncSession,
        openai_client=None,
        image_data: Optional[dict] = None,
        file_data: Optional[dict] = None,
        use_search: bool = False
    ) -> str:
        
        logger.info(f"🧠 Procesando: Sess={session_id} | Mod={model_name} | Search={use_search}")

        history = await get_history(session_id, db)
        await save_message(session_id, "user", prompt, db)

        try:
            provider = ChatService.get_provider(model_name, openai_client)
            
            reply = await provider.generate(
                prompt=prompt, 
                history=history, 
                image_data=image_data, 
                file_data=file_data,
                use_search=use_search
            )

            await save_message(session_id, "model", reply, db)
            return reply

        except RateLimitError:
            logger.warning(f"⏳ Rate Limit en proveedor LLM (Sess={session_id})")
            raise HTTPException(status_code=429, detail="LLM Rate Limit Exceeded. Please try again later.")
            
        except APIConnectionError:
            logger.error(f"🔌 Error de conexión con LLM (Sess={session_id})")
            raise HTTPException(status_code=503, detail="LLM Provider Unavailable.")

        except Exception as e:
            logger.exception(f"🔥 Error critico en LLM: {e}")
            raise HTTPException(status_code=500, detail="Internal Error processing chat.")