"""Integration tests for the relevance write path (migration 0024).

Relevance lives in the narrow `record_relevance` table, seeded by an AFTER
INSERT trigger on `bibliographic_records` and filled by the nightly recompute's
chunked upsert. These run against a real Postgres (testcontainers, schema via
Alembic) because the trigger, the array `unnest` upsert and the FK cascade are
all database behaviour a unit test can't see.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
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

from bibliohack.catalog.application.use_cases.recompute_relevance import RecomputeRelevance
from bibliohack.catalog.domain.relevance import RelevanceResult
from bibliohack.catalog.infrastructure.postgres.relevance_repository import (
    PostgresRelevanceRepository,
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


async def _insert_record(session: AsyncSession, titn: int, *, pub_year: int = 2020) -> UUID:
    record_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO bibliographic_records "
            "(id, titn, title, pub_year, source_url, source_hash) "
            "VALUES (:id, :titn, :title, :pub_year, :url, :hash)"
        ),
        {
            "id": record_id,
            "titn": titn,
            "title": f"Libro {titn}",
            "pub_year": pub_year,
            "url": f"https://opac.example/{titn}",
            "hash": b"\x00",
        },
    )
    return record_id


async def _relevance_rows(session: AsyncSession) -> dict[UUID, tuple[float, object, object]]:
    rows = await session.execute(
        text("SELECT record_id, score, components, updated_at FROM record_relevance")
    )
    return {rid: (score, comps, updated) for rid, score, comps, updated in rows.all()}


async def test_insert_trigger_seeds_an_unscored_row(session: AsyncSession) -> None:
    rid = await _insert_record(session, 101)

    rows = await _relevance_rows(session)

    assert rows[rid] == (0.0, None, None)


async def test_recompute_scores_every_record(session: AsyncSession) -> None:
    old = await _insert_record(session, 201, pub_year=1950)
    new = await _insert_record(session, 202, pub_year=2025)

    summary = await RecomputeRelevance(repo=PostgresRelevanceRepository(session)).execute()

    assert summary.scored == summary.written == 2
    rows = await _relevance_rows(session)
    for rid in (old, new):
        score, components, updated_at = rows[rid]
        assert 0.0 <= score <= 1.0
        assert isinstance(components, dict)
        assert {"demand", "holdings", "recency", "completeness"} <= components.keys()
        assert updated_at is not None
    # Same everything but publication year: the newer book ranks higher.
    assert rows[new][0] > rows[old][0]


async def test_write_scores_chunks_and_upserts(session: AsyncSession) -> None:
    ids = [await _insert_record(session, 300 + i) for i in range(5)]
    # Drop one seeded row: the upsert must still create it.
    await session.execute(
        text("DELETE FROM record_relevance WHERE record_id = :id"), {"id": ids[0]}
    )
    results = [
        (rid, RelevanceResult(score=0.1 * (i + 1), components={"demand": 0.5}))
        for i, rid in enumerate(ids)
    ]

    written = await PostgresRelevanceRepository(session).write_scores(results, chunk_size=2)

    assert written == 5
    rows = await _relevance_rows(session)
    for i, rid in enumerate(ids):
        assert rows[rid][0] == pytest.approx(0.1 * (i + 1))
        assert rows[rid][1] == {"demand": 0.5}
        assert isinstance(rows[rid][2], datetime)
        assert rows[rid][2].tzinfo is not None
        assert rows[rid][2] <= datetime.now(UTC)


async def test_deleting_a_record_cascades_to_its_relevance(session: AsyncSession) -> None:
    rid = await _insert_record(session, 401)

    await session.execute(text("DELETE FROM bibliographic_records WHERE id = :id"), {"id": rid})

    assert rid not in await _relevance_rows(session)
