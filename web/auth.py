"""Web Admin authentication backends."""

from __future__ import annotations

import logging
import secrets
import time


logger = logging.getLogger(__name__)


class MemoryAuthBackend:
    """In-memory auth/session backend for single-process deployment."""

    name = "memory"

    def __init__(self) -> None:
        self._sessions: dict[str, float] = {}
        self._login_hits: dict[str, list[float]] = {}

    async def create_session(self, *, username: str, ttl_seconds: int) -> str:
        del username
        sid = secrets.token_urlsafe(32)
        self._sessions[sid] = time.time() + max(60, ttl_seconds)
        return sid

    async def is_session_valid(self, sid: str) -> bool:
        if not sid:
            return False
        now = time.time()
        expires_at = self._sessions.get(sid, 0)
        if expires_at <= now:
            self._sessions.pop(sid, None)
            return False
        return True

    async def delete_session(self, sid: str) -> None:
        if sid:
            self._sessions.pop(sid, None)

    async def allow_login_attempt(self, *, ip: str, window_seconds: int, max_attempts: int) -> bool:
        now = time.time()
        hits = [ts for ts in self._login_hits.get(ip, []) if now - ts <= window_seconds]
        if len(hits) >= max_attempts:
            self._login_hits[ip] = hits
            return False
        hits.append(now)
        self._login_hits[ip] = hits
        return True

    async def close(self) -> None:
        return None

    async def clear_all_sessions(self) -> int:
        count = len(self._sessions)
        self._sessions.clear()
        return count


class RedisAuthBackend:
    """Redis-backed auth/session backend for multi-instance deployment."""

    name = "redis"

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    @staticmethod
    def _session_key(sid: str) -> str:
        return f"webadmin:sess:{sid}"

    @staticmethod
    def _rate_key(ip: str) -> str:
        return f"webadmin:rate:{ip}"

    async def create_session(self, *, username: str, ttl_seconds: int) -> str:
        sid = secrets.token_urlsafe(32)
        await self._redis.setex(self._session_key(sid), max(60, ttl_seconds), username)
        return sid

    async def is_session_valid(self, sid: str) -> bool:
        if not sid:
            return False
        return bool(await self._redis.exists(self._session_key(sid)))

    async def delete_session(self, sid: str) -> None:
        if sid:
            await self._redis.delete(self._session_key(sid))

    async def allow_login_attempt(self, *, ip: str, window_seconds: int, max_attempts: int) -> bool:
        key = self._rate_key(ip)
        count = int(await self._redis.incr(key))
        if count == 1:
            await self._redis.expire(key, max(60, window_seconds))
        return count <= max_attempts

    async def close(self) -> None:
        close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def validate_connection(self) -> None:
        await self._redis.ping()

    async def clear_all_sessions(self) -> int:
        deleted = 0
        async for key in self._redis.scan_iter(match="webadmin:sess:*", count=200):
            deleted += int(await self._redis.delete(key))
        return deleted


def require_secret(value: str | None, *, name: str) -> str:
    secret = str(value or "").strip()
    if not secret:
        raise RuntimeError(f"{name} must be configured.")
    return secret


def build_auth_backend(
    redis_url: str | None,
    *,
    allow_memory_fallback: bool = False,
):
    redis_url = (redis_url or "").strip()
    if not redis_url:
        logger.info("Web auth backend: memory")
        return MemoryAuthBackend()

    try:
        import redis.asyncio as redis

        client = redis.from_url(redis_url, decode_responses=True)
        logger.info("Web auth backend: redis (%s)", redis_url)
        return RedisAuthBackend(client)
    except Exception as exc:
        if allow_memory_fallback:
            logger.error("Redis unavailable; explicitly falling back to memory. reason=%s", exc)
            return MemoryAuthBackend()
        raise RuntimeError(
            "WEB_ADMIN_REDIS_URL is configured, but Redis auth backend is unavailable. "
            "Install redis dependency, fix WEB_ADMIN_REDIS_URL, or explicitly set "
            "WEB_ADMIN_REDIS_ALLOW_MEMORY_FALLBACK=true."
        ) from exc
