"""Rate limiting — Fase 9.1 Redis sliding-window + IP fallback.

Uses slowapi Limiter with Redis storage when REDIS_URL is configured
(distributed), otherwise in-memory. Additionally exposes
RedisSlidingWindow for per-principal (user / api-key) sliding-window
checks used by quotas & API-key limiter.
"""
import time
import logging
from typing import Optional

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

logger = logging.getLogger(__name__)

# Primary Limiter (decorator-based) — distributed via Redis when available
# slowapi supports storage_uri="redis://..." or "memory://"
try:
    _storage = settings.REDIS_URL if settings.REDIS_URL else "memory://"
except Exception:
    _storage = "memory://"

# slowapi's RedisStorage is optional; if redis not installed, Limiter falls back to memory
try:
    limiter = Limiter(key_func=get_remote_address, storage_uri=_storage, strategy="fixed-window")
    logger.info(f"RateLimiter storage={_storage}")
except Exception as e:
    logger.warning(f"RateLimiter fallback to memory (redis storage init failed: {e})")
    limiter = Limiter(key_func=get_remote_address)


# ---- Redis sliding-window helper (per-user / per-api-key) ----

class RedisSlidingWindow:
    """Async sliding-window limiter backed by Redis ZSET, with in-memory fallback.

    Key pattern: `rl:{key}:{window}` -> sorted set of request timestamps.
    Uses ZADD + ZREMRANGEBYSCORE + ZCARD + EXPIRE.
    Falls back to dict + deque when Redis unavailable (tests).
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or getattr(settings, "REDIS_URL", None)
        self._fallback_store: dict[str, list[float]] = {}
        self._redis = None

    async def _get_redis(self):
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
            logger.warning(f"RedisSlidingWindow: redis unavailable {e}, using memory fallback")
            self._redis = None
            return None

    async def is_allowed(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Return (allowed, remaining). Uses sliding window."""
        now = time.time()
        window_start = now - window_seconds
        redis = await self._get_redis()
        redis_key = f"rl:{key}:{window_seconds}"

        if redis is not None:
            try:
                pipe = redis.pipeline()
                # Add current timestamp
                pipe.zadd(redis_key, {str(now): now})
                # Remove old entries
                pipe.zremrangebyscore(redis_key, 0, window_start)
                # Count remaining
                pipe.zcard(redis_key)
                # Expire
                pipe.expire(redis_key, window_seconds + 5)
                results = await pipe.execute()
                count = results[2] if len(results) >= 3 else 0
                allowed = count <= limit
                remaining = max(0, limit - count)
                # If over limit, we already added; but we need to enforce: if over limit, don't count this request?
                # Keep simple: if over limit, remove the just-added entry and deny
                if not allowed:
                    await redis.zrem(redis_key, str(now))
                return allowed, remaining
            except Exception as e:
                logger.warning(f"Redis sliding window error {e}, fallback to memory")
                # fall through to memory

        # In-memory fallback
        lst = self._fallback_store.get(redis_key, [])
        # prune old
        lst = [t for t in lst if t > window_start]
        if len(lst) < limit:
            lst.append(now)
            self._fallback_store[redis_key] = lst
            return True, limit - len(lst)
        else:
            self._fallback_store[redis_key] = lst
            return False, 0

    async def reset(self, key: str, window_seconds: int = 60):
        """Clear window for key (useful for tests)."""
        redis_key = f"rl:{key}:{window_seconds}"
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.delete(redis_key)
            except Exception:
                pass
        self._fallback_store.pop(redis_key, None)


# Singleton for app-wide use
redis_sliding_window = RedisSlidingWindow()

# Helper key func that prefers principal over IP (used for per-user limits)
def make_principal_key(request, prefix: str = "user") -> str:
    """Build rate-limit key from Authorization principal if available, else IP."""
    # Try to extract user id / api key from request state if set by deps
    # Fallback to IP
    try:
        # If auth was already resolved, request.state.principal_id may exist
        pid = getattr(request.state, "principal_id", None)
        if pid:
            return f"{prefix}:{pid}"
    except Exception:
        pass
    # Fallback to IP
    try:
        return f"ip:{get_remote_address(request)}"
    except Exception:
        return "ip:unknown"
