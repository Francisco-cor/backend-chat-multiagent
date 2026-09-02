import hashlib
import json
import logging
import asyncio
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _dummy_vector(text: str, dim: int = 64) -> List[float]:
    """Deterministic dummy embedding via hash (for tests / no-API)."""
    # Use hashlib sha256 to generate deterministic floats
    h = hashlib.sha256(text.encode()).hexdigest()
    # Convert hex to floats 0-1
    vec = []
    for i in range(dim):
        # Take 2 hex chars per dim, cycle through hash
        hex_slice = h[(i * 2) % len(h) : (i * 2) % len(h) + 2]
        if len(hex_slice) < 2:
            hex_slice = "00"
        val = int(hex_slice, 16) / 255.0
        # Center around 0
        vec.append(val * 2 - 1)
    # Normalize to unit length
    norm = sum(x * x for x in vec) ** 0.5
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


class EmbeddingService:
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = (provider or getattr(settings, "EMBEDDING_PROVIDER", "dummy") or "dummy").lower()
        self.model = model or getattr(settings, "EMBEDDING_MODEL", "text-embedding-3-small")
        self.dim = getattr(settings, "EMBEDDING_DIM", 64)

    async def embed_text(self, text: str) -> List[float]:
        # Try real providers, fallback to dummy
        if self.provider == "openai" and settings.OPENAI_API_KEY:
            try:
                return await self._embed_openai(text)
            except Exception as e:
                logger.warning(f"OpenAI embed failed, fallback dummy: {e}")
        if self.provider == "gemini" and settings.GOOGLE_API_KEY:
            try:
                return await self._embed_gemini(text)
            except Exception as e:
                logger.warning(f"Gemini embed failed, fallback dummy: {e}")
        # Dummy
        return await asyncio.to_thread(_dummy_vector, text, self.dim)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        # Batch with concurrency limit
        results: List[List[float]] = []
        for t in texts:
            vec = await self.embed_text(t)
            results.append(vec)
        return results

    async def _embed_openai(self, text: str) -> List[float]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        resp = await client.embeddings.create(model=self.model, input=text)
        return resp.data[0].embedding

    async def _embed_gemini(self, text: str) -> List[float]:
        from google import genai

        client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        # Gemini embedding via client.models.embed_content (sync)
        def _call():
            result = client.models.embed_content(model=self.model, contents=text)
            # result.embeddings[0].values
            emb = result.embeddings[0].values if hasattr(result, "embeddings") else result
            return list(emb)

        return await asyncio.to_thread(_call)

    @staticmethod
    def serialize(vec: List[float]) -> str:
        return json.dumps(vec)

    @staticmethod
    def deserialize(s: str) -> List[float]:
        try:
            return json.loads(s)
        except Exception:
            return []


# Global singleton for reuse
embedding_service = EmbeddingService()
