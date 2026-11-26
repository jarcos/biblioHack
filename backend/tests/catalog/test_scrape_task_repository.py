"""Integration tests for `PostgresScrapeTaskRepository`.

We run against a real Postgres via testcontainers — `timescale/timescaledb-ha:pg16`
matches what we use in docker-compose (bundles TimescaleDB + pgvector).
The migration is applied with Alembic so the schema is exactly what
production sees.

Marked `integration` so quick CI runs can skip them; full CI applies them.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from bibliohack.catalog.application.ports import TaskState
from bibliohack.catalog.domain.titn import Titn
from bibliohack.catalog.infrastructure.postgres.scrape_task_repository import (
    PostgresScrapeTaskRepository,
)

pytestmark = pytest.mark.integration


# ───────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def postgres_container() -> AsyncIterator[PostgresContainer]:
    container = PostgresContainer(image="timescale/timescaledb-ha:pg16")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest_asyncio.fixture(scope="module")
async def applied_db(postgres_container: PostgresContainer) -> AsyncIterator[str]:
    """Apply Alembic migrations to the testcontainer DB; return the async URL."""
    sync_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+psycopg"
    )
    async_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )

    # Point Alembic at our migrations folder.
    backend_root = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))
    # Settings reads DATABASE_URL from env; override it for this run.
    # get_settings() is @lru_cache'd — clear the cache so the new env vars
    # propagate to alembic env.py.
    os.environ["DATABASE_URL"] = async_url
    os.environ["DATABASE_URL_SYNC"] = sync_url
    from bibliohack.shared.infrastructure.settings import get_settings

    get_settings.cache_clear()

    command.upgrade(alembic_cfg, "head")
    yield async_url


@pytest_asyncio.fixture
async def session(applied_db: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        # Each test gets a transaction that is rolled back at the end —
        # state never leaks between tests.
        await s.begin()
        try:
            yield s
        finally:
            await s.rollback()
    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> PostgresScrapeTaskRepository:
    return PostgresScrapeTaskRepository(session)


# ───────────────────────────────────────────────────────────────
# Seeding
# ───────────────────────────────────────────────────────────────


async def test_seed_range_inserts_discovered_rows(
    repo: PostgresScrapeTaskRepository,
) -> None:
    inserted = await repo.seed_range(Titn(1), Titn(100))
    assert inserted == 100

    counts = await repo.count_by_state()
    assert counts.get(TaskState.DISCOVERED) == 100
    assert counts.total == 100


async def test_seed_range_is_idempotent(repo: PostgresScrapeTaskRepository) -> None:
    await repo.seed_range(Titn(1), Titn(50))
    second = await repo.seed_range(Titn(40), Titn(60))
    # Only the 10 new TITNs (51..60) should have been inserted.
    assert second == 10


async def test_seed_one_returns_false_on_duplicate(
    repo: PostgresScrapeTaskRepository,
) -> None:
    assert await repo.seed_one(Titn(42)) is True
    assert await repo.seed_one(Titn(42)) is False


async def test_seed_range_rejects_inverted_bounds(
    repo: PostgresScrapeTaskRepository,
) -> None:
    with pytest.raises(ValueError, match="must be <="):
        await repo.seed_range(Titn(100), Titn(50))


# ───────────────────────────────────────────────────────────────
# Claim + state transitions
# ───────────────────────────────────────────────────────────────


async def test_claim_next_batch_returns_lowest_titns_first(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await repo.seed_range(Titn(1), Titn(10))
    batch = await repo.claim_next_batch(limit=3)
    assert [int(t.titn) for t in batch] == [1, 2, 3]


async def test_claim_respects_limit(repo: PostgresScrapeTaskRepository) -> None:
    await repo.seed_range(Titn(1), Titn(50))
    batch = await repo.claim_next_batch(limit=7)
    assert len(batch) == 7


async def test_claim_returns_empty_when_no_due_rows(
    repo: PostgresScrapeTaskRepository,
) -> None:
    # No seeds — table is empty.
    assert await repo.claim_next_batch(limit=5) == []


async def test_mark_parsed_records_hash_and_advances_state(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await repo.seed_one(Titn(7))
    await repo.mark_parsed(Titn(7), source_hash=b"\xde\xad\xbe\xef" * 8)

    task = await repo.get(Titn(7))
    assert task is not None
    assert task.status is TaskState.PARSED
    assert task.source_hash == b"\xde\xad\xbe\xef" * 8
    assert task.source_seen_at is not None
    assert task.attempt_count == 1


async def test_mark_not_found_does_not_set_retry(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await repo.seed_one(Titn(99))
    await repo.mark_not_found(Titn(99))
    task = await repo.get(Titn(99))
    assert task is not None
    assert task.status is TaskState.NOT_FOUND
    assert task.next_retry_at is None


async def test_mark_failed_records_error_and_retry_time(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await repo.seed_one(Titn(13))
    retry = datetime.now(tz=UTC) + timedelta(minutes=30)
    await repo.mark_failed(Titn(13), error="upstream 503", next_retry_at=retry)

    task = await repo.get(Titn(13))
    assert task is not None
    assert task.status is TaskState.FAILED
    assert task.last_error == "upstream 503"
    assert task.next_retry_at is not None
    # Allow a small precision delta — Postgres rounds to microseconds.
    assert abs((task.next_retry_at - retry).total_seconds()) < 1


async def test_failed_rows_with_future_retry_are_not_claimed(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await repo.seed_one(Titn(13))
    future = datetime.now(tz=UTC) + timedelta(hours=1)
    await repo.mark_failed(Titn(13), error="busy", next_retry_at=future)

    # The default `claim_next_batch` only looks at DISCOVERED, so this should
    # return nothing.
    assert await repo.claim_next_batch(limit=5) == []

    # But asking for FAILED + filtering on retry time also returns nothing
    # because next_retry_at is in the future.
    assert await repo.claim_next_batch(limit=5, states=[TaskState.FAILED]) == []


async def test_failed_rows_with_past_retry_are_eligible(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await repo.seed_one(Titn(13))
    past = datetime.now(tz=UTC) - timedelta(seconds=1)
    await repo.mark_failed(Titn(13), error="old failure", next_retry_at=past)

    claimed = await repo.claim_next_batch(limit=5, states=[TaskState.FAILED])
    assert len(claimed) == 1
    assert int(claimed[0].titn) == 13


# ───────────────────────────────────────────────────────────────
# Count + read
# ───────────────────────────────────────────────────────────────


async def test_count_by_state_returns_per_state_histogram(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await repo.seed_range(Titn(1), Titn(10))
    await repo.mark_parsed(Titn(1), source_hash=b"\x00" * 32)
    await repo.mark_parsed(Titn(2), source_hash=b"\x01" * 32)
    await repo.mark_not_found(Titn(3))
    counts = await repo.count_by_state()
    assert counts.get(TaskState.PARSED) == 2
    assert counts.get(TaskState.NOT_FOUND) == 1
    assert counts.get(TaskState.DISCOVERED) == 7
    assert counts.total == 10


async def test_get_returns_none_for_unknown_titn(
    repo: PostgresScrapeTaskRepository,
) -> None:
    assert await repo.get(Titn(999_999)) is None


# ───────────────────────────────────────────────────────────────
# Refresh sweep (M2 availability worker)
# ───────────────────────────────────────────────────────────────


async def test_refresh_claim_returns_due_parsed_records(session: AsyncSession) -> None:
    """`require_refresh_due` claims `parsed` rows whose refresh_due_at has passed.

    A repo with a negative refresh_interval schedules the next refresh in the
    past on mark_parsed, so the row is immediately due for a re-scrape.
    """
    repo = PostgresScrapeTaskRepository(session, refresh_interval=timedelta(seconds=-1))
    await repo.seed_one(Titn(500))
    await repo.mark_parsed(Titn(500), source_hash=b"\x00" * 32)

    # The default (initial-crawl) claim only looks at DISCOVERED — a parsed row
    # is invisible there.
    assert await repo.claim_next_batch(limit=5) == []

    # The refresh claim picks it up: refresh_due_at is in the past.
    claimed = await repo.claim_next_batch(
        limit=5, states=[TaskState.PARSED], require_refresh_due=True
    )
    assert [int(task.titn) for task in claimed] == [500]


async def test_refresh_claim_skips_not_yet_due(session: AsyncSession) -> None:
    """A record refreshed with a future due date is not re-claimed yet."""
    repo = PostgresScrapeTaskRepository(session, refresh_interval=timedelta(days=7))
    await repo.seed_one(Titn(501))
    await repo.mark_parsed(Titn(501), source_hash=b"\x00" * 32)

    claimed = await repo.claim_next_batch(
        limit=5, states=[TaskState.PARSED], require_refresh_due=True
    )
    assert claimed == []


# ───────────────────────────────────────────────────────────────
# Requeueing failed tasks (catalog requeue-failed)
# ───────────────────────────────────────────────────────────────


async def _fail(repo: PostgresScrapeTaskRepository, titn: int, error: str, times: int = 1) -> None:
    await repo.seed_one(Titn(titn))
    for _ in range(times):
        await repo.mark_failed(Titn(titn), error=error, next_retry_at=None)


async def test_requeue_failed_moves_matching_rows_back_to_discovered(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await _fail(repo, 701, "persist error: ProgrammingError")
    await _fail(repo, 702, "persist error: ProgrammingError")
    await _fail(repo, 703, "parse error: No title (T245 / .doc_title) in HTML")

    requeued = await repo.requeue_failed(error_prefix="persist error", max_attempts=5)

    assert requeued == 2
    for titn in (701, 702):
        task = await repo.get(Titn(titn))
        assert task is not None
        assert task.status is TaskState.DISCOVERED
        assert task.next_retry_at is None
        # The history stays: the attempt count is what caps a retry loop.
        assert task.attempt_count == 1
    untouched = await repo.get(Titn(703))
    assert untouched is not None
    assert untouched.status is TaskState.FAILED
    # Requeued rows are claimable by the ordinary worker again.
    claimed = await repo.claim_next_batch(limit=5)
    assert [int(t.titn) for t in claimed] == [701, 702]


async def test_requeue_failed_without_prefix_takes_every_failure(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await _fail(repo, 711, "persist error: ProgrammingError")
    await _fail(repo, 712, "parse error: No TITN field")

    assert await repo.requeue_failed(error_prefix=None, max_attempts=5) == 2


async def test_requeue_failed_respects_the_attempt_cap(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await _fail(repo, 721, "persist error: ProgrammingError", times=3)

    assert await repo.requeue_failed(error_prefix=None, max_attempts=3) == 0
    assert await repo.requeue_failed(error_prefix=None, max_attempts=4) == 1


async def test_requeue_failed_respects_the_limit_lowest_titn_first(
    repo: PostgresScrapeTaskRepository,
) -> None:
    for titn in (733, 731, 732):
        await _fail(repo, titn, "persist error: ProgrammingError")

    assert await repo.requeue_failed(error_prefix=None, max_attempts=5, limit=2) == 2

    claimed = await repo.claim_next_batch(limit=5)
    assert [int(t.titn) for t in claimed] == [731, 732]


async def test_requeue_failed_treats_like_wildcards_in_the_prefix_literally(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await _fail(repo, 741, "persist error: ProgrammingError")

    assert await repo.requeue_failed(error_prefix="%", max_attempts=5) == 0
    assert await repo.requeue_failed(error_prefix="persist_error", max_attempts=5) == 0


async def test_failed_error_counts_groups_by_error_prefix(
    repo: PostgresScrapeTaskRepository,
) -> None:
    await _fail(repo, 751, "persist error: ProgrammingError")
    await _fail(repo, 752, "persist error: ProgrammingError")
    await _fail(repo, 753, "parse error: No title (T245 / .doc_title) in HTML")
    await repo.seed_one(Titn(754))  # discovered, not failed: never counted

    counts = await repo.failed_error_counts(prefix_length=15)

    assert [(c.error_prefix, c.count) for c in counts] == [
        ("persist error: ", 2),
        ("parse error: No", 1),
    ]
