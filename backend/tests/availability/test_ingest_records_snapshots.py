"""End-to-end: a catalog ingest with the snapshot repo wired drops one
availability_snapshot per persisted copy.

This is the M2 contract that the worker depends on. We run the real
`PostgresCatalogIngestRepository` against a real Postgres (testcontainers
+ Alembic) with the `availability_repository` collaborator wired in,
then count the snapshots that landed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from bibliohack.availability.infrastructure.postgres.availability_snapshot_repository import (
    PostgresAvailabilitySnapshotRepository,
)
from bibliohack.catalog.infrastructure.absysnet.parser import ParsedCopy, ParsedRecord
from bibliohack.catalog.infrastructure.postgres.catalog_ingest_repository import (
    PostgresCatalogIngestRepository,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration


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


# ───────────────────────────────────────────────────────────────


async def test_ingest_drops_one_snapshot_per_copy(applied_db: str) -> None:
    """A scrape with N parsed ejemplares lands N snapshot rows."""
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as s, s.begin():
            await s.execute(
                text(
                    "TRUNCATE availability_snapshots, copies, contributors, "
                    "subjects, isbns, bibliographic_records, branches "
                    "RESTART IDENTITY CASCADE"
                )
            )

        async with factory() as s, s.begin():
            availability_repo = PostgresAvailabilitySnapshotRepository(s)
            ingest = PostgresCatalogIngestRepository(s, availability_repository=availability_repo)

            result = await ingest.persist_parsed_record(
                parsed=ParsedRecord(
                    titn=42,
                    title="Test record",
                    authors=("Test, Author",),
                    publisher="Test Press",
                    record_type="a",
                    bibliographic_level="m",
                ),
                copies=[
                    ParsedCopy(
                        branch_code="HU01",
                        branch_name="Huelva Provincial",
                        signature="A 1",
                        barcode="BC-1",
                        raw_status="Disponible",
                    ),
                    ParsedCopy(
                        branch_code="HU01",
                        branch_name="Huelva Provincial",
                        signature="A 2",
                        barcode="BC-2",
                        raw_status="Prestado",
                    ),
                    ParsedCopy(
                        branch_code="SE01",
                        branch_name="Sevilla Provincial",
                        signature="B 1",
                        barcode="BC-3",
                        raw_status="En inventario",
                    ),
                ],
                source_url="https://example.test/?TITN=42",
                source_hash=b"\xab" * 32,
            )

        # 3 copies, 3 snapshots in this scrape.
        assert result.copies_persisted == 3
        assert result.snapshots_persisted == 3

        async with factory() as s:
            rows = (
                await s.execute(
                    text(
                        "SELECT status FROM availability_snapshots "
                        "ORDER BY status"
                    )
                )
            ).all()
        statuses = [r[0] for r in rows]
        # Domain mapping: Disponible→available, Prestado→loaned,
        # 'En inventario'→unavailable.
        assert statuses == ["available", "loaned", "unavailable"]
    finally:
        await engine.dispose()


async def test_ingest_without_availability_repo_skips_snapshots(applied_db: str) -> None:
    """Backwards compatibility — ingest still works without the repo."""
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as s, s.begin():
            await s.execute(
                text(
                    "TRUNCATE availability_snapshots, copies, contributors, "
                    "subjects, isbns, bibliographic_records, branches "
                    "RESTART IDENTITY CASCADE"
                )
            )

        async with factory() as s, s.begin():
            ingest = PostgresCatalogIngestRepository(s)  # no availability_repository
            result = await ingest.persist_parsed_record(
                parsed=ParsedRecord(
                    titn=43,
                    title="No-snapshot record",
                    record_type="a",
                    bibliographic_level="m",
                ),
                copies=[
                    ParsedCopy(
                        branch_code="HU01",
                        branch_name="Huelva Provincial",
                        signature="X",
                        barcode="BC-X",
                        raw_status="Disponible",
                    ),
                ],
                source_url="https://example.test/?TITN=43",
                source_hash=b"\xcd" * 32,
            )

        assert result.copies_persisted == 1
        assert result.snapshots_persisted == 0

        async with factory() as s:
            count = (
                await s.execute(text("SELECT COUNT(*) FROM availability_snapshots"))
            ).scalar_one()
        assert count == 0
    finally:
        await engine.dispose()
