"""PostgresHealthReader against a real Postgres (testcontainers, schema via Alembic).

The queries run every 10 minutes on the NAS next to the crawl, so they are
chosen to be cheap (measured on production 2026-11-26) — except the record
count, which the use case only asks for every few hours.
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from bibliohack.availability.infrastructure.postgres.availability_snapshot_repository import (
    PostgresAvailabilitySnapshotRepository,
)
from bibliohack.catalog.domain.titn import Titn
from bibliohack.catalog.infrastructure.absysnet.parser import ParsedCopy, ParsedRecord
from bibliohack.catalog.infrastructure.postgres.catalog_ingest_repository import (
    PostgresCatalogIngestRepository,
)
from bibliohack.catalog.infrastructure.postgres.scrape_task_repository import (
    PostgresScrapeTaskRepository,
)
from bibliohack.ops.domain.health import CursorProgress
from bibliohack.ops.infrastructure.postgres_health_reader import PostgresHealthReader
from bibliohack.shared.infrastructure.schema_revision import EXPECTED_SCHEMA_REVISION

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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


async def _ingest(session: AsyncSession, titn: int) -> None:
    ingest = PostgresCatalogIngestRepository(
        session, availability_repository=PostgresAvailabilitySnapshotRepository(session)
    )
    await ingest.persist_parsed_record(
        parsed=ParsedRecord(
            titn=titn, title=f"Libro {titn}", record_type="a", bibliographic_level="m"
        ),
        copies=[
            ParsedCopy(
                branch_code="HU01",
                branch_name="Huelva Provincial",
                signature=f"A {titn}",
                barcode=f"BC-{titn}",
                raw_status="Disponible",
            )
        ],
        source_url=f"https://example.test/?TITN={titn}",
        source_hash=b"\xab" * 32,
    )


async def test_an_empty_catalogue_reads_as_nothing_yet(session: AsyncSession) -> None:
    reader = PostgresHealthReader(session)

    assert await reader.schema_revision() == EXPECTED_SCHEMA_REVISION
    assert await reader.last_availability_snapshot_at() is None
    assert await reader.last_relevance_update_at() is None
    assert await reader.scrape_failures_since(datetime.now(tz=UTC) - timedelta(hours=1)) == 0
    assert await reader.discovery_cursors() == []
    assert await reader.record_counts() == (0, 0)


async def test_reads_the_latest_snapshot_and_the_record_counts(session: AsyncSession) -> None:
    before = datetime.now(tz=UTC) - timedelta(seconds=5)
    await _ingest(session, 501)
    await _ingest(session, 502)
    await session.execute(
        text(
            "UPDATE bibliographic_records "
            "SET embedding = array_fill(0.03125::real, ARRAY[1024])::vector WHERE titn = 501"
        )
    )
    reader = PostgresHealthReader(session)

    snapshot_at = await reader.last_availability_snapshot_at()
    assert snapshot_at is not None
    assert snapshot_at >= before
    assert await reader.record_counts() == (2, 1)


async def test_relevance_freshness_comes_from_the_scored_rows(session: AsyncSession) -> None:
    await _ingest(session, 601)
    await _ingest(session, 602)
    scored_at = datetime(2026, 11, 26, 4, 0, tzinfo=UTC)
    await session.execute(
        text("UPDATE record_relevance SET score = 0.5, updated_at = :at"), {"at": scored_at}
    )

    assert await PostgresHealthReader(session).last_relevance_update_at() == scored_at


async def test_counts_only_recent_failures(session: AsyncSession) -> None:
    tasks = PostgresScrapeTaskRepository(session)
    for titn in (701, 702, 703):
        await tasks.seed_one(Titn(titn))
    await tasks.mark_failed(Titn(701), error="persist error: ProgrammingError", next_retry_at=None)
    await tasks.mark_failed(Titn(702), error="persist error: ProgrammingError", next_retry_at=None)
    await session.execute(
        text(
            "UPDATE scrape_tasks SET last_attempted_at = now() - interval '2 hours' WHERE titn = 702"
        )
    )

    since = datetime.now(tz=UTC) - timedelta(hours=1)
    assert await PostgresHealthReader(session).scrape_failures_since(since) == 1


async def test_reads_the_discovery_cursors(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO discovery_cursors (expression, next_offset, total) VALUES "
            "('(@fepu>=2024)', 56944, 63262), ('__backlist_titn__', 10, NULL)"
        )
    )

    assert await PostgresHealthReader(session).discovery_cursors() == [
        CursorProgress(expression="(@fepu>=2024)", next_offset=56_944, total=63_262),
        CursorProgress(expression="__backlist_titn__", next_offset=10, total=None),
    ]


async def test_a_broken_query_reads_as_unknown_and_the_rest_still_work(
    session: AsyncSession,
) -> None:
    # A drifted schema can break any one query. The drift itself must still be
    # reported, so each fact is read on its own and a failure means "unknown".
    await _ingest(session, 801)
    await session.execute(text("DROP TABLE record_relevance CASCADE"))
    reader = PostgresHealthReader(session)

    assert await reader.last_relevance_update_at() is None
    assert await reader.schema_revision() == EXPECTED_SCHEMA_REVISION
    assert await reader.last_availability_snapshot_at() is not None


async def test_every_reader_method_survives_a_missing_table(session: AsyncSession) -> None:
    await session.execute(
        text(
            "DROP TABLE alembic_version, availability_snapshots, scrape_tasks, "
            "discovery_cursors, bibliographic_records CASCADE"
        )
    )
    reader = PostgresHealthReader(session)

    assert await reader.schema_revision() is None
    assert await reader.last_availability_snapshot_at() is None
    assert await reader.scrape_failures_since(datetime.now(tz=UTC)) is None
    assert await reader.discovery_cursors() == []
    assert await reader.record_counts() is None
