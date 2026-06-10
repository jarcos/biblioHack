"""Redis fixed-window rate limiter (identity Phase 5).

INCR + EXPIRE per (scope, caller) key: the first hit in a window creates the
counter with a TTL, subsequent hits increment it, and the request is denied
once the counter passes the limit. Fixed windows allow up to 2x the limit
across a boundary — irrelevant at these thresholds and much simpler than
sliding logs.

Fails OPEN: if Redis is down the request proceeds (and we log). Locking
every user out of login because the session store is having a moment is a
worse failure than briefly losing brute-force protection — and without
Redis, login is broken anyway.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from redis.asyncio import Redis


class RedisRateLimiter:
    """Fixed-window counter over redis-py's asyncio client."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        """Record one hit; True when still within the limit."""
        try:
            count = await cast("Awaitable[int]", self._redis.incr(f"rl:{key}"))
            if count == 1:
                await cast("Awaitable[bool]", self._redis.expire(f"rl:{key}", window_seconds))
        except Exception as exc:  # fail-open by design (see module docstring)
            structlog.get_logger().warning(
                "ratelimit.unavailable_failing_open",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return True
        return count <= limit
