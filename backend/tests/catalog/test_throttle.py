"""Tests for the TokenBucket rate limiter.

We inject a virtual clock and a fake sleep so the tests run instantly and
deterministically — no `time.sleep` (or `await asyncio.sleep`) on the real
clock.
"""

from __future__ import annotations

import asyncio

import pytest

from bibliohack.catalog.infrastructure.absysnet.throttle import TokenBucket


class _VirtualTime:
    """A monotonic clock + sleep pair we can advance from the test."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def vtime() -> _VirtualTime:
    return _VirtualTime()


def _bucket(vtime: _VirtualTime, *, rate: float = 1.0, burst: int = 1) -> TokenBucket:
    return TokenBucket(
        rate_per_second=rate,
        burst=burst,
        jitter_seconds=0.0,  # disable jitter for determinism
        _clock=vtime.clock,
        _sleep=vtime.sleep,  # type: ignore[arg-type]
    )


async def test_first_token_is_immediate(vtime: _VirtualTime) -> None:
    bucket = _bucket(vtime)
    await bucket.acquire()
    assert vtime.sleeps == []  # no waiting on the very first request


async def test_second_token_within_a_second_must_wait(vtime: _VirtualTime) -> None:
    bucket = _bucket(vtime, rate=1.0, burst=1)
    await bucket.acquire()
    await bucket.acquire()
    # Second acquire had to wait ~1 s for refill.
    assert len(vtime.sleeps) == 1
    assert 0.9 <= vtime.sleeps[0] <= 1.1


async def test_burst_lets_us_drain_then_wait(vtime: _VirtualTime) -> None:
    # burst=3 means three quick requests then catch-up time.
    bucket = _bucket(vtime, rate=1.0, burst=3)
    for _ in range(3):
        await bucket.acquire()
    assert vtime.sleeps == []
    await bucket.acquire()
    assert len(vtime.sleeps) == 1


async def test_higher_rate_means_shorter_wait(vtime: _VirtualTime) -> None:
    bucket = _bucket(vtime, rate=10.0, burst=1)
    await bucket.acquire()
    await bucket.acquire()
    # Refill rate is 10/s, so deficit-of-1 token needs ~0.1 s.
    assert 0.08 <= vtime.sleeps[0] <= 0.12


@pytest.mark.parametrize("bad_rate", [0, -1, -0.001])
def test_non_positive_rate_rejected(bad_rate: float, vtime: _VirtualTime) -> None:
    with pytest.raises(ValueError, match="rate_per_second must be positive"):
        _bucket(vtime, rate=bad_rate)


def test_zero_burst_rejected(vtime: _VirtualTime) -> None:
    with pytest.raises(ValueError, match="burst must be at least 1"):
        _bucket(vtime, burst=0)


async def test_concurrent_acquires_are_serialised(vtime: _VirtualTime) -> None:
    """The lock guarantees fairness — no race ever consumes more tokens than exist."""
    bucket = _bucket(vtime, rate=1.0, burst=1)
    results = await asyncio.gather(
        bucket.acquire(),
        bucket.acquire(),
        bucket.acquire(),
    )
    # All three eventually completed; two of them had to sleep.
    assert results == [None, None, None]
    assert len(vtime.sleeps) == 2
