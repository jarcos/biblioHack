"""Integration tests for `PostgresEmbeddingRepository`'s backfill queue.

The embed job works through ~1.5M records a few hundred at a time, so the
order of the queue decides which books get semantic search, "más como este"
and recommendations first. It follows the precomputed relevance score
(`record_relevance`, migration 0024), so the books readers are likely to meet
are embedded before the long tail. Runs against a real Postgres
(testcontainers, schema via Alembic) because the order is a join against the
trigger-seeded relevance table.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from bibliohack.catalog.infrastructure.postgres.embedding_repository import (
    PostgresEmbeddingRepository,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

pytestmark = pytest.mark.integration


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
    sync_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+psycopg"
    )
    async_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )
    backend_root = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))
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
        # One rolled-back transaction per test — nothing leaks between tests.
        await s.begin()
        try:
            yield s
        finally:
            await s.rollback()
    await engine.dispose()


async def _insert_record(session: AsyncSession, titn: int, *, score: float) -> UUID:
    record_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO bibliographic_records (id, titn, title, source_url, source_hash) "
            "VALUES (:id, :titn, :title, :url, :hash)"
        ),
        {
            "id": record_id,
            "titn": titn,
            "title": f"Libro {titn}",
            "url": f"https://opac.example/{titn}",
            "hash": b"\x00",
        },
    )
    # The AFTER INSERT trigger seeded the relevance row; give it a score.
    await session.execute(
        text("UPDATE record_relevance SET score = :score WHERE record_id = :id"),
        {"score": score, "id": record_id},
    )
    return record_id


def _unit_vector() -> list[float]:
    return [1.0] + [0.0] * 1023


async def test_queue_follows_relevance_not_titn(session: AsyncSession) -> None:
    low = await _insert_record(session, 9001, score=0.1)
    high = await _insert_record(session, 9002, score=0.9)
    mid = await _insert_record(session, 9003, score=0.5)

    queue = await PostgresEmbeddingRepository(session).records_needing_embedding(limit=3)

    assert [r.record_id for r in queue] == [high, mid, low]


async def test_queue_skips_records_that_already_have_a_vector(session: AsyncSession) -> None:
    embedded = await _insert_record(session, 9101, score=0.9)
    pending = await _insert_record(session, 9102, score=0.2)
    repo = PostgresEmbeddingRepository(session)
    await repo.store_embedding(embedded, _unit_vector())

    queue = await repo.records_needing_embedding(limit=5)

    assert [r.record_id for r in queue] == [pending]
    assert await repo.count_missing() == 1


async def test_equal_scores_fall_back_to_newest_titn_first(session: AsyncSession) -> None:
    older = await _insert_record(session, 9201, score=0.0)
    newer = await _insert_record(session, 9202, score=0.0)

    queue = await PostgresEmbeddingRepository(session).records_needing_embedding(limit=2)

    assert [r.record_id for r in queue] == [newer, older]


async def test_limit_bounds_the_batch(session: AsyncSession) -> None:
    for i in range(4):
        await _insert_record(session, 9300 + i, score=i / 10)

    queue = await PostgresEmbeddingRepository(session).records_needing_embedding(limit=2)

    assert len(queue) == 2


async def test_sample_embedded_returns_stored_vectors_for_a_parity_check(
    session: AsyncSession,
) -> None:
    embedded = await _insert_record(session, 9401, score=0.3)
    await _insert_record(session, 9402, score=0.8)  # no vector: never sampled
    repo = PostgresEmbeddingRepository(session)
    await repo.store_embedding(embedded, _unit_vector())

    sample = await repo.sample_embedded(limit=5)

    assert [s.record.record_id for s in sample] == [embedded]
    assert sample[0].record.title == "Libro 9401"
    assert sample[0].vector == pytest.approx(_unit_vector())
