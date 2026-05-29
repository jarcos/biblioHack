"""Integration tests for `PostgresAvailabilitySnapshotRepository`.

Spins up a real Postgres (timescale/timescaledb-ha:pg16, matches docker-
compose), applies the full Alembic migration chain so we exercise the
real hypertable, then seeds one bibliographic_records + one copies row
so the snapshot FK has something to point at.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from bibliohack.availability.domain.snapshot import AvailabilitySnapshot
from bibliohack.availability.domain.status import AvailabilityStatus
from bibliohack.availability.infrastructure.postgres.availability_snapshot_repository import (
    PostgresAvailabilitySnapshotRepository,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

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


@pytest_asyncio.fixture
async def seeded_copy_ids(applied_db: str) -> AsyncIterator[tuple[UUID, UUID]]:
    """Insert one bibliographic_record + two copies, return their UUIDs."""
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    record_id = uuid4()
    copy_a = uuid4()
    copy_b = uuid4()
    async with factory() as s, s.begin():
        # Wipe relevant tables (these tests share the module-scoped DB).
        await s.execute(
            text(
                "TRUNCATE availability_snapshots, copies, bibliographic_records, branches "
                "RESTART IDENTITY CASCADE"
            )
        )
        await s.execute(
            text("INSERT INTO branches (code, name) VALUES ('HU01', 'Huelva Provincial')")
        )
        await s.execute(
            text(
                "INSERT INTO bibliographic_records "
                "(id, titn, title, source_url, source_hash) "
                "VALUES (:id, 1, 'Cien años', 'https://example.test', :sh)"
            ),
            {"id": record_id, "sh": b"\x00" * 32},
        )
        await s.execute(
            text(
                "INSERT INTO copies (id, record_id, branch_code, barcode) "
                "VALUES (:a, :rid, 'HU01', 'BC-A'), (:b, :rid, 'HU01', 'BC-B')"
            ),
            {"a": copy_a, "b": copy_b, "rid": record_id},
        )
    yield copy_a, copy_b
    await engine.dispose()


@pytest_asyncio.fixture
async def session(applied_db: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ───────────────────────────────────────────────────────────────


async def test_record_inserts_snapshots(
    session: AsyncSession, seeded_copy_ids: tuple[UUID, UUID]
) -> None:
    copy_a, copy_b = seeded_copy_ids
    repo = PostgresAvailabilitySnapshotRepository(session)
    observed = datetime(2026, 5, 29, 9, 0, 0, tzinfo=UTC)
    async with session.begin():
        n = await repo.record(
            [
                AvailabilitySnapshot(copy_a, observed, AvailabilityStatus.AVAILABLE),
                AvailabilitySnapshot(copy_b, observed, AvailabilityStatus.LOANED),
            ]
        )
    assert n == 2

    rows = (
        await session.execute(
            text("SELECT copy_id, status FROM availability_snapshots ORDER BY status")
        )
    ).all()
    by_status = {r[1]: r[0] for r in rows}
    assert by_status == {"available": copy_a, "loaned": copy_b}


async def test_record_is_idempotent_on_same_pk(
    session: AsyncSession, seeded_copy_ids: tuple[UUID, UUID]
) -> None:
    """A repeat call with the same (copy_id, observed_at) inserts 0 rows."""
    copy_a, _ = seeded_copy_ids
    repo = PostgresAvailabilitySnapshotRepository(session)
    observed = datetime(2026, 5, 29, 10, 0, 0, tzinfo=UTC)
    snap = AvailabilitySnapshot(copy_a, observed, AvailabilityStatus.AVAILABLE)

    async with session.begin():
        first = await repo.record([snap])
    async with session.begin():
        second = await repo.record([snap])

    assert first == 1
    assert second == 0


async def test_record_persists_due_back_at(
    session: AsyncSession, seeded_copy_ids: tuple[UUID, UUID]
) -> None:
    copy_a, _ = seeded_copy_ids
    repo = PostgresAvailabilitySnapshotRepository(session)
    observed = datetime(2026, 5, 29, 11, 0, 0, tzinfo=UTC)
    due = (observed + timedelta(days=21)).date()
    snap = AvailabilitySnapshot(copy_a, observed, AvailabilityStatus.LOANED, due_back_at=due)

    async with session.begin():
        n = await repo.record([snap])
    assert n == 1

    row = (
        await session.execute(
            text(
                "SELECT due_back_at FROM availability_snapshots "
                "WHERE copy_id = :cid AND observed_at = :obs"
            ),
            {"cid": copy_a, "obs": observed},
        )
    ).scalar_one()
    assert row == due


async def test_record_handles_empty_input(session: AsyncSession) -> None:
    repo = PostgresAvailabilitySnapshotRepository(session)
    async with session.begin():
        n = await repo.record([])
    assert n == 0
