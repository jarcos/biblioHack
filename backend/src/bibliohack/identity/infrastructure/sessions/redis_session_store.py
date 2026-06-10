"""Redis-backed `SessionStore` — opaque session ids with a TTL.

Layout:
- ``session:{id}`` → user id string, EX = ttl (the session itself).
- ``user_sessions:{user_id}`` → set of that user's session ids, used by
  `delete_for_user` ("log out everywhere" after a password reset). The set
  carries the same TTL, refreshed on each new session; stale members are
  harmless (their ``session:`` keys are gone, GET just misses).

Session ids are 256-bit random URL-safe strings — unguessable, so they need
no signature; possession is proof.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from redis.asyncio import Redis

_SESSION_PREFIX = "session:"
_USER_SESSIONS_PREFIX = "user_sessions:"


class RedisSessionStore:
    """Concrete `SessionStore` over redis-py's asyncio client."""

    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def create(self, user_id: str) -> str:
        session_id = secrets.token_urlsafe(32)
        pipe = self._redis.pipeline()
        pipe.set(f"{_SESSION_PREFIX}{session_id}", user_id, ex=self._ttl)
        pipe.sadd(f"{_USER_SESSIONS_PREFIX}{user_id}", session_id)
        pipe.expire(f"{_USER_SESSIONS_PREFIX}{user_id}", self._ttl)
        await pipe.execute()
        return session_id

    async def get(self, session_id: str) -> str | None:
        value = await self._redis.get(f"{_SESSION_PREFIX}{session_id}")
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def delete(self, session_id: str) -> None:
        user_id = await self.get(session_id)
        pipe = self._redis.pipeline()
        pipe.delete(f"{_SESSION_PREFIX}{session_id}")
        if user_id is not None:
            pipe.srem(f"{_USER_SESSIONS_PREFIX}{user_id}", session_id)
        await pipe.execute()

    async def delete_for_user(self, user_id: str) -> None:
        # redis-py types smembers as `Awaitable[set] | set` (sync/async union);
        # on the asyncio client it is always awaitable.
        members = await cast(
            "Awaitable[set[str | bytes]]",
            self._redis.smembers(f"{_USER_SESSIONS_PREFIX}{user_id}"),
        )
        session_ids = [m.decode() if isinstance(m, bytes) else str(m) for m in members]
        pipe = self._redis.pipeline()
        for session_id in session_ids:
            pipe.delete(f"{_SESSION_PREFIX}{session_id}")
        pipe.delete(f"{_USER_SESSIONS_PREFIX}{user_id}")
        await pipe.execute()
