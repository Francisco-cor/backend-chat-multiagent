"""Transcription Service — Fase 7.3

Supports audio → text via:
 - OpenAI Whisper (openai.audio.transcriptions.create) if OPENAI_API_KEY present
 - Fallback dummy for tests / without key

Also vision helper for image base64 → description hint.
"""
import base64
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def transcribe_audio(audio_base64: str, mime_type: str = "audio/webm", client=None) -> str:
    """
    Transcribe audio base64 to text. Returns transcript or error string.
    If client not provided and OPENAI_API_KEY available, creates one transiently.
    """
    try:
        audio_bytes = await asyncio.to_thread(base64.b64decode, audio_base64)
    except Exception as e:
        return f"Error decoding audio: {e}"

    # Try OpenAI Whisper if client available
    if client is None:
        try:
            from app.core.config import settings
            if settings.OPENAI_API_KEY:
                from openai import AsyncOpenAI

                client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        except Exception:
            client = None

    if client is not None:
        try:
            import io

            # openai expects file-like with .name
            buf = io.BytesIO(audio_bytes)
            buf.name = f"audio.{mime_type.split('/')[-1] or 'webm'}"
            # Some OpenAI clients use audio.transcriptions
            resp = await client.audio.transcriptions.create(
                model="whisper-1",
                file=buf,
            )
            text = getattr(resp, "text", None) or getattr(resp, "transcript", "") or str(resp)
            return text.strip() if isinstance(text, str) else str(text).strip()
        except Exception as e:
            logger.warning(f"Whisper transcription failed, fallback dummy: {e}")

    # Fallback dummy: return placeholder with size info (useful for tests)
    return f"[transcript dummy: {len(audio_bytes)} bytes, mime={mime_type}]"


async def describe_image_dummy(image_base64: str, mime_type: str) -> str:
    """Fallback when vision not needed — just validates."""
    try:
        await asyncio.to_thread(base64.b64decode, image_base64)
        return f"[image {mime_type} ok]"
    except Exception as e:
        return f"Error image: {e}"
