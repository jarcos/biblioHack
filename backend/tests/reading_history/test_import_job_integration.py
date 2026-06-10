"""Integration tests for `PostgresImportJobRepository` and the worker pipeline.

Real Postgres via testcontainers. The final test drives the actual worker
coroutine (`process_import_job`) end-to-end against the database — claim,
parse, match, stats — exactly what the Dramatiq actor wraps, minus the
Redis transport.
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository
from bibliohack.reading_history.application.use_cases.import_shelf import ImportStats
from bibliohack.reading_history.domain.import_job import ImportJobStatus
from bibliohack.reading_history.infrastructure.postgres.import_job_repository import (
    PostgresImportJobRepository,
)

pytestmark = pytest.mark.integration

GOODREADS_CSV = (
    "Book Id,Title,Author,ISBN13,My Rating,Exclusive Shelf,My Review,Date Read,Date Added\n"
    '1,"Cien años de soledad","Gabriel García Márquez",,5,read,,2024/01/02,2023/12/01\n'
    '2,"Nada","Carmen Laforet",,0,to-read,,,\n'
)


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
    async with factory() as setup, setup.begin():
        await setup.execute(text("TRUNCATE users, import_jobs, shelf_entries CASCADE"))
    async with factory() as s, s.begin():
        yield s
    await engine.dispose()


async def _reader(session: AsyncSession, email: str = "reader@example.com") -> str:
    user = User.register(email=Email(email), password_hash=PasswordHash("$argon2id$fake"))
    await PostgresUserRepository(session).add(user)
    return str(user.id)


async def test_lifecycle_claim_is_single_shot(session: AsyncSession) -> None:
    repo = PostgresImportJobRepository(session)
    uid = await _reader(session)

    job_id = await repo.create(user_id=uid, filename="lib.csv", csv_content=GOODREADS_CSV)
    view = await repo.get_view(job_id, user_id=uid)
    assert view is not None
    assert view.status is ImportJobStatus.QUEUED

    claimed = await repo.claim(job_id)
    assert claimed is not None
    assert claimed.user_id == uid
    assert "Cien años" in claimed.csv_content
    assert await repo.claim(job_id) is None  # already running — redelivery is a no-op

    await repo.mark_done(job_id, ImportStats(total=2, inserted=2, unmatched=2))
    done = await repo.get_view(job_id, user_id=uid)
    assert done is not None
    assert done.status is ImportJobStatus.DONE
    assert done.total == 2
    assert done.finished_at is not None


async def test_get_view_is_owner_scoped_and_failure_recorded(session: AsyncSession) -> None:
    repo = PostgresImportJobRepository(session)
    uid = await _reader(session)
    other = await _reader(session, "other@example.com")

    job_id = await repo.create(user_id=uid, filename=None, csv_content="x")
    assert await repo.get_view(job_id, user_id=other) is None  # not yours → invisible
    assert await repo.get_view("not-a-uuid", user_id=uid) is None

    await repo.mark_failed(job_id, "boom " * 1000)
    failed = await repo.get_view(job_id, user_id=uid)
    assert failed is not None
    assert failed.status is ImportJobStatus.FAILED
    assert failed.error is not None
    assert len(failed.error) <= 2000  # long errors are truncated


async def test_worker_pipeline_end_to_end(applied_db: str) -> None:
    """`process_import_job` (what the Dramatiq actor runs) resolves a real job."""
    from bibliohack.reading_history.infrastructure.dramatiq.actors import process_import_job

    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup, setup.begin():
        await setup.execute(text("TRUNCATE users, import_jobs, shelf_entries CASCADE"))
    async with factory() as setup, setup.begin():
        uid = await _reader(setup)
        job_id = await PostgresImportJobRepository(setup).create(
            user_id=uid, filename="lib.csv", csv_content=GOODREADS_CSV
        )

    await process_import_job(job_id)

    async with factory() as check:
        view = await PostgresImportJobRepository(check).get_view(job_id, user_id=uid)
        assert view is not None
        assert view.status is ImportJobStatus.DONE
        assert view.total == 2
        assert view.unmatched == 2  # empty catalogue — nothing to match against
        shelf_count = (await check.execute(text("SELECT count(*) FROM shelf_entries"))).scalar_one()
        assert shelf_count == 2
    await engine.dispose()
