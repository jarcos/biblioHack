"""Shared cross-context test fakes."""

from __future__ import annotations


class AllowAllRateLimiter:
    """Rate limiter that never throttles — for tests that aren't about limits.

    Unit-test apps must override `get_rate_limiter` with this: the real
    provider talks to whatever Redis answers at `settings.redis_url`, so a
    developer machine running Redis would accumulate fixed-window counters
    across test runs and start failing tests with spurious 429s.
    """

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        return True
