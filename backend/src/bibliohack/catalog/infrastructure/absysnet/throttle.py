"""Token-bucket rate limiter — async, fair, jittered.

Independent of any specific scraper or HTTP client. Test it in isolation:
give it a clock and a budget, watch it block.

The bucket holds at most `burst` tokens; refill happens continuously at
`rate_per_second`. `acquire()` waits until at least one token is available,
then consumes it. A small random jitter on the wait time prevents thundering
herds when multiple workers wake up together.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass
class TokenBucket:
    """Async token-bucket rate limiter.

    For our scraper: `rate_per_second=1.0`, `burst=1` is the conservative
    default. That gives us at most one request per second on average, with
    no bursting. Tests can use much higher rates with virtual clocks.
    """

    rate_per_second: float
    burst: int = 1
    jitter_seconds: float = 0.1
    # Injected for testability. Defaults: monotonic clock + asyncio.sleep.
    _clock: Callable[[], float] = field(default_factory=lambda: asyncio.get_event_loop().time)
    _sleep: Callable[[float], Awaitable[None]] = field(
        default_factory=lambda: asyncio.sleep,
    )
    _tokens: float = field(init=False)
    _updated_at: float = field(init=False)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        if self.rate_per_second <= 0:
            msg = "rate_per_second must be positive"
            raise ValueError(msg)
        if self.burst < 1:
            msg = "burst must be at least 1"
            raise ValueError(msg)
        self._tokens = float(self.burst)
        self._updated_at = self._clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._updated_at)
        self._tokens = min(float(self.burst), self._tokens + elapsed * self.rate_per_second)
        self._updated_at = now

    async def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        async with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            # How long until we have one full token?
            deficit = 1.0 - self._tokens
            wait_for = deficit / self.rate_per_second
            if self.jitter_seconds > 0:
                wait_for += random.uniform(0.0, self.jitter_seconds)  # noqa: S311
            await self._sleep(wait_for)
            self._refill()
            self._tokens = max(0.0, self._tokens - 1.0)
