"""End-to-end integration test for `ScrapeOneTask`.

Exercises the full pipeline against a real Postgres (testcontainers):
- Seed a `discovered` row.
- Run `ScrapeOneTask.execute` with a stub gateway that returns our
  on-disk `titn_1.html` fixture.
- Assert `bibliographic_records`, `contributors`, `branches`, `copies`
  all have the right rows, and `scrape_tasks` is now `parsed`.

This is the load-bearing test for M1's scrape pipeline. If this fails,
the worker doesn't work.
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
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from bibliohack.catalog.application.ports import (
    FetchOutcome,
    FetchResult,
    TaskState,
)
from bibliohack.catalog.application.use_cases.scrape_one_task import (
    ScrapeOneTask,
    ScrapeStepOutcome,
)
from bibliohack.catalog.domain.titn import Titn
from bibliohack.catalog.infrastructure.postgres.catalog_ingest_repository import (
    PostgresCatalogIngestRepository,
)
from bibliohack.catalog.infrastructure.postgres.models import (
    BibliographicRecordModel,
    ContributorModel,
)
from bibliohack.catalog.infrastructure.postgres.scrape_task_repository import (
    PostgresScrapeTaskRepository,
)
from bibliohack.holdings.infrastructure.postgres.models import BranchModel, CopyModel

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.integration


# ───────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def postgres_container() -> AsyncIterator[PostgresContainer]:
    container = PostgresContainer(image="pgvector/pgvector:pg16")
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
        # Manual transaction so the test can flush and read its own writes
        # without committing — at the end we roll back to leave the DB pristine.
        await s.begin()
        try:
            # Truncate any state left over from a prior test in this module.
            await s.execute(
                text(
                    "TRUNCATE bibliographic_records, scrape_tasks, copies, "
                    "branches, contributors, subjects, isbns "
                    "RESTART IDENTITY CASCADE"
                )
            )
            yield s
        finally:
            await s.rollback()
    await engine.dispose()


# ───────────────────────────────────────────────────────────────
# Test doubles
# ───────────────────────────────────────────────────────────────


class StubOpacGateway:
    """Returns scripted FetchResults — one per TITN."""

    def __init__(self, *, html_by_titn: dict[int, str]) -> None:
        self._html = html_by_titn
        self.calls: list[int] = []

    async def fetch_record(self, titn: Titn) -> FetchResult:
        self.calls.append(int(titn))
        html = self._html.get(int(titn))
        if html is None:
            return FetchResult(
                titn=titn,
                outcome=FetchOutcome.NOT_FOUND,
                url=f"https://test/?TITN={int(titn)}",
                final_url=f"https://test/?TITN={int(titn)}",
                status_code=200,
                html="<html>no result</html>",
                latency_ms=1,
                bytes_in=10,
            )
        return FetchResult(
            titn=titn,
            outcome=FetchOutcome.OK,
            url=f"https://test/?TITN={int(titn)}",
            final_url=f"https://test/?TITN={int(titn)}&session=abc",
            status_code=200,
            html=html,
            latency_ms=42,
            bytes_in=len(html),
        )


# ───────────────────────────────────────────────────────────────
# Tests
# ───────────────────────────────────────────────────────────────


async def test_scrape_one_task_full_pipeline_against_real_fixture(
    session: AsyncSession,
) -> None:
    """The big one: seed TITN=1, fetch returns titn_1.html, expect everything
    parsed and persisted, scrape_tasks row transitioned to parsed."""
    # Arrange
    real_html = (FIXTURES / "titn_1.html").read_text(encoding="utf-8")
    task_repo = PostgresScrapeTaskRepository(session)
    ingest_repo = PostgresCatalogIngestRepository(session)
    gateway = StubOpacGateway(html_by_titn={1: real_html})
    await task_repo.seed_one(Titn(1))
    await session.flush()

    # Act
    step = ScrapeOneTask(task_repository=task_repo, ingest_repository=ingest_repo, gateway=gateway)
    result = await step.execute()

    # Assert: pipeline outcome
    assert result.outcome is ScrapeStepOutcome.PERSISTED
    assert result.titn == 1
    assert gateway.calls == [1]

    # Assert: bibliographic_records row exists with the right title
    record = (
        await session.execute(
            select(BibliographicRecordModel).where(BibliographicRecordModel.titn == 1)
        )
    ).scalar_one()
    assert record.title == "0044 y medio IBM y compañía Arantza"
    assert "Guadalhorce" in (record.publisher or "")
    assert record.source_hash is not None
    assert len(record.source_hash) == 32  # sha256

    # Assert: at least one author was persisted
    contributors = (
        (
            await session.execute(
                select(ContributorModel).where(ContributorModel.record_id == record.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(c.name == "Bornoy, Pepe" for c in contributors)

    # Assert: 4 branches discovered, 4 copies persisted
    branch_count = (await session.execute(select(func.count(BranchModel.code)))).scalar_one()
    assert branch_count == 4
    copy_count = (
        await session.execute(
            select(func.count(CopyModel.id)).where(CopyModel.record_id == record.id)
        )
    ).scalar_one()
    assert copy_count == 4

    # Assert: scrape_tasks row now in PARSED state with source_hash set
    task = await task_repo.get(Titn(1))
    assert task is not None
    assert task.status is TaskState.PARSED
    assert task.source_hash == record.source_hash
    assert task.attempt_count == 1


async def test_scrape_one_task_returns_no_work_on_empty_queue(
    session: AsyncSession,
) -> None:
    task_repo = PostgresScrapeTaskRepository(session)
    ingest_repo = PostgresCatalogIngestRepository(session)
    gateway = StubOpacGateway(html_by_titn={})

    result = await ScrapeOneTask(
        task_repository=task_repo, ingest_repository=ingest_repo, gateway=gateway
    ).execute()

    assert result.outcome is ScrapeStepOutcome.NO_WORK
    assert gateway.calls == []


async def test_scrape_one_task_marks_not_found(session: AsyncSession) -> None:
    task_repo = PostgresScrapeTaskRepository(session)
    ingest_repo = PostgresCatalogIngestRepository(session)
    gateway = StubOpacGateway(html_by_titn={})  # nothing returns OK
    await task_repo.seed_one(Titn(99))
    await session.flush()

    result = await ScrapeOneTask(
        task_repository=task_repo, ingest_repository=ingest_repo, gateway=gateway
    ).execute()

    assert result.outcome is ScrapeStepOutcome.NOT_FOUND
    task = await task_repo.get(Titn(99))
    assert task is not None
    assert task.status is TaskState.NOT_FOUND


async def test_scrape_one_task_handles_transient_error_with_backoff(
    session: AsyncSession,
) -> None:
    task_repo = PostgresScrapeTaskRepository(session)
    ingest_repo = PostgresCatalogIngestRepository(session)

    class _FailingGateway:
        async def fetch_record(self, _titn: Titn) -> FetchResult:
            from bibliohack.catalog.application.ports import OpacUnavailableError

            msg = "simulated 503"
            raise OpacUnavailableError(msg)

    await task_repo.seed_one(Titn(13))
    await session.flush()

    result = await ScrapeOneTask(
        task_repository=task_repo,
        ingest_repository=ingest_repo,
        gateway=_FailingGateway(),  # type: ignore[arg-type]
    ).execute()

    assert result.outcome is ScrapeStepOutcome.TRANSIENT_ERROR
    task = await task_repo.get(Titn(13))
    assert task is not None
    assert task.status is TaskState.FAILED
    assert task.last_error is not None
    assert "simulated 503" in task.last_error
    # Backoff schedule: first transient = 30s, so next_retry_at is roughly now+30s.
    assert task.next_retry_at is not None
    delta = task.next_retry_at - datetime.now(tz=UTC)
    assert timedelta(seconds=15) < delta < timedelta(seconds=90)


async def test_rescrape_updates_record_in_place(session: AsyncSession) -> None:
    """A second scrape of the same TITN must update the existing row, not
    insert a new one."""
    real_html = (FIXTURES / "titn_1.html").read_text(encoding="utf-8")
    task_repo = PostgresScrapeTaskRepository(session)
    ingest_repo = PostgresCatalogIngestRepository(session)
    gateway = StubOpacGateway(html_by_titn={1: real_html})

    # First scrape
    await task_repo.seed_one(Titn(1))
    await session.flush()
    await ScrapeOneTask(
        task_repository=task_repo, ingest_repository=ingest_repo, gateway=gateway
    ).execute()

    # Re-seed the same task (would normally happen via a refresh cadence —
    # for the test we just flip its status back manually).
    await session.execute(text("UPDATE scrape_tasks SET status='discovered' WHERE titn=1"))
    await session.flush()

    # Second scrape — should hit the same record id
    result = await ScrapeOneTask(
        task_repository=task_repo, ingest_repository=ingest_repo, gateway=gateway
    ).execute()
    assert result.outcome is ScrapeStepOutcome.PERSISTED

    # Still exactly one record row
    n_records = (
        await session.execute(select(func.count(BibliographicRecordModel.id)))
    ).scalar_one()
    assert n_records == 1
