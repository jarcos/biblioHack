"""Rate-limiter tests — counter logic, fail-open, and the HTTP 429 path."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import get_rate_limiter
from bibliohack.shared.infrastructure.ratelimit import RedisRateLimiter


class FakeRedis:
    """Just enough of redis-py's asyncio surface for the limiter."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True


class BrokenRedis:
    async def incr(self, key: str) -> int:
        msg = "redis is down"
        raise ConnectionError(msg)


class DenyAllLimiter:
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        return False


async def test_counts_per_key_and_sets_the_window_once() -> None:
    redis = FakeRedis()
    limiter = RedisRateLimiter(redis)  # type: ignore[arg-type]

    assert await limiter.hit("login:1.2.3.4", limit=2, window_seconds=60) is True
    assert await limiter.hit("login:1.2.3.4", limit=2, window_seconds=60) is True
    assert await limiter.hit("login:1.2.3.4", limit=2, window_seconds=60) is False
    # A different caller has its own counter.
    assert await limiter.hit("login:5.6.7.8", limit=2, window_seconds=60) is True
    assert redis.expirations == {"rl:login:1.2.3.4": 60, "rl:login:5.6.7.8": 60}


async def test_fails_open_when_redis_is_down() -> None:
    limiter = RedisRateLimiter(BrokenRedis())  # type: ignore[arg-type]
    assert await limiter.hit("login:1.2.3.4", limit=1, window_seconds=60) is True


def test_exceeded_limit_is_a_429() -> None:
    app = create_app()
    app.dependency_overrides[get_rate_limiter] = DenyAllLimiter
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login", json={"email": "a@example.com", "password": "long-enough-pass"}
        )
    assert response.status_code == 429
    assert "slow down" in response.json()["detail"]


def test_token_consume_endpoints_are_limited() -> None:
    """verify + password/reset are throttled too — they brute-force the token space."""
    app = create_app()
    app.dependency_overrides[get_rate_limiter] = DenyAllLimiter
    with TestClient(app) as client:
        verify = client.post("/api/auth/verify", json={"token": "tok"})
        reset = client.post(
            "/api/auth/password/reset", json={"token": "tok", "password": "long-enough-pass"}
        )
    assert verify.status_code == 429
    assert reset.status_code == 429
