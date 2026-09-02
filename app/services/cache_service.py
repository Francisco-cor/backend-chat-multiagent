"""Cache Service — Fase 11.2 Redis cache for embeddings + LLM semantic cache.

- embeddings: key = f"emb:{provider}:{hash(text)}" TTL 24h
- LLM responses: key = hash(prompt+model+history_hash+tools_hash) TTL 10m
Fallback to in-memory dict if Redis unavailable (tests).
"""
import hashlib
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _hash_key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
        h.update(b"|")
    return h.hexdigest()[:32]


class CacheService:
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self._redis = None
        self._mem: dict[str, tuple[Any, float]] = {}
        self._mem_embedding: dict[str, Any] = {}
        # lazy import settings
        try:
            from app.core.config import settings
            self._enabled = getattr(settings, "CACHE_ENABLED", True)
            self._ttl_llm = getattr(settings, "LLM_CACHE_TTL", 600)
            self._ttl_emb = getattr(settings, "CACHE_EMBEDDING_TTL", 86400)
            if not redis_url:
                self.redis_url = getattr(settings, "REDIS_URL", None)
        except Exception:
            self._enabled = True
            self._ttl_llm = 600
            self._ttl_emb = 86400

    async def _get_redis(self):
        if not self._enabled:
            return None
        if self._redis is not None:
            return self._redis
        if not self.redis_url:
            return None
        try:
            import redis.asyncio as redis  # type: ignore
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
            await self._redis.ping()
            return self._redis
        except Exception as e:
            logger.warning(f"Cache redis unavailable, fallback memory: {e}")
            self._redis = None
            return None

    # --- LLM semantic cache ---

    def _llm_key(self, prompt: str, model: str, history_hash: str = "", tools_hash: str = "") -> str:
        return f"llm:{_hash_key(prompt, model, history_hash, tools_hash)}"

    async def get_llm(self, prompt: str, model: str, history_hash: str = "", tools_hash: str = "") -> Optional[str]:
        if not self._enabled:
            return None
        key = self._llm_key(prompt, model, history_hash, tools_hash)
        r = await self._get_redis()
        if r is not None:
            try:
                v = await r.get(key)
                if v:
                    logger.info(f"LLM cache hit {key}")
                    return v
            except Exception as e:
                logger.warning(f"LLM cache get failed: {e}")
        # memory fallback
        import time
        entry = self._mem.get(key)
        if entry:
            val, exp = entry
            if exp > time.time():
                logger.info(f"LLM cache hit mem {key}")
                return val
            else:
                self._mem.pop(key, None)
        return None

    async def set_llm(self, prompt: str, model: str, response: str, history_hash: str = "", tools_hash: str = "") -> None:
        if not self._enabled:
            return
        key = self._llm_key(prompt, model, history_hash, tools_hash)
        r = await self._get_redis()
        if r is not None:
            try:
                await r.setex(key, self._ttl_llm, response)
                return
            except Exception as e:
                logger.warning(f"LLM cache set failed: {e}")
        import time
        self._mem[key] = (response, time.time() + self._ttl_llm)

    # --- Embedding cache ---

    def _emb_key(self, text: str, provider: str, model: str) -> str:
        return f"emb:{provider}:{model}:{_hash_key(text)}"

    async def get_embedding(self, text: str, provider: str = "dummy", model: str = "dummy") -> Optional[list[float]]:
        if not self._enabled:
            return None
        key = self._emb_key(text, provider, model)
        r = await self._get_redis()
        if r is not None:
            try:
                v = await r.get(key)
                if v:
                    return json.loads(v)
            except Exception:
                pass
        return self._mem_embedding.get(key)

    async def set_embedding(self, text: str, provider: str = "dummy", model: str = "unused", embedding: list[float] = None) -> None:
        if not self._enabled or embedding is None:
            return
        # support positional quirk: called as set_embedding(text, provider, model, embedding) or set_embedding(text, embedding)
        # normalize
        if isinstance(model, list) and embedding is None:
            embedding = model  # type: ignore
            model = "dummy"
        key = self._emb_key(text, provider, model)  # type: ignore
        r = await self._get_redis()
        if r is not None:
            try:
                await r.setex(key, self._ttl_emb, json.dumps(embedding))
                return
            except Exception:
                pass
        self._mem_embedding[key] = embedding

    async def clear(self):
        self._mem.clear()
        self._mem_embedding.clear()
        r = await self._get_redis()
        if r is not None:
            try:
                # flush only our prefix keys
                async for k in r.scan_iter("llm:*"):
                    await r.delete(k)
                async for k in r.scan_iter("emb:*"):
                    await r.delete(k)
            except Exception:
                pass


# singleton
cache_service = CacheService()


def history_hash(history) -> str:
    """Deterministic hash of history (list of ConversationHistory/message dicts)."""
    try:
        parts = []
        for m in history or []:
            role = getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else "")
            content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else "")
            parts.append(f"{role}:{content[:200]}")
        return _hash_key("|".join(parts[-10:]))  # last 10 for stability
    except Exception:
        return ""
