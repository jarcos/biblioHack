"""Integration tests for the shelf re-match repository methods (real Postgres).

Covers the two new `PostgresShelfRepository` methods the demand-driven fetcher
relies on — `iter_unmatched` (eligibility scan, ordering) and `link_match`
(linking an entry to a now-present record, which drops it out of the scan) — plus
a RematchShelf end-to-end pass against the DB. Real Postgres via testcontainers,
so it also exercises the `20260622_0020` migration (applied to head).
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

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository
from bibliohack.reading_history.application.use_cases.rematch_shelf import RematchShelf
from bibliohack.reading_history.domain.shelf import MatchVia
from bibliohack.reading_history.infrastructure.postgres.shelf_repository import (
    PostgresShelfRepository,
)

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
    async with factory() as setup, setup.begin():
        await setup.execute(
            text("TRUNCATE users, bibliographic_records, isbns, shelf_entries CASCADE")
        )
    async with factory() as s, s.begin():
        yield s
    await engine.dispose()


async def _reader(session: AsyncSession, email: str = "reader@example.com") -> str:
    user = User.register(email=Email(email), password_hash=PasswordHash("$argon2id$fake"))
    await PostgresUserRepository(session).add(user)
    return str(user.id)


async def _insert_entry(
    session: AsyncSession,
    *,
    user_id: str,
    source_book_id: str,
    title: str,
    author: str | None = None,
    isbn_13: str | None = None,
    last_resolved_at: datetime | None = None,
) -> str:
    entry_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO shelf_entries "
            "(id, user_id, source, source_book_id, title, author, isbn_13, shelf, "
            " last_resolved_at) "
            "VALUES (:id, :uid, 'goodreads', :sbid, :title, :author, :isbn, 'read', "
            " :last)"
        ),
        {
            "id": entry_id,
            "uid": user_id,
            "sbid": source_book_id,
            "title": title,
            "author": author,
            "isbn": isbn_13,
            "last": last_resolved_at,
        },
    )
    return str(entry_id)


_titn_seq = 1_000_000


async def _insert_record(session: AsyncSession, *, title: str, isbn_13: str | None = None) -> str:
    global _titn_seq
    _titn_seq += 1
    record_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO bibliographic_records (id, titn, title, source_url, source_hash) "
            "VALUES (:id, :titn, :title, :url, :hash)"
        ),
        {
            "id": record_id,
            "titn": _titn_seq,
            "title": title,
            "url": f"https://opac.example/{_titn_seq}",
            "hash": b"\x00" * 32,
        },
    )
    if isbn_13 is not None:
        await session.execute(
            text("INSERT INTO isbns (record_id, isbn) VALUES (:rid, :isbn)"),
            {"rid": record_id, "isbn": isbn_13},
        )
    return str(record_id)


async def test_iter_unmatched_orders_never_tried_first(session: AsyncSession) -> None:
    uid = await _reader(session)
    await _insert_entry(
        session,
        user_id=uid,
        source_book_id="tried",
        title="Tried",
        last_resolved_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    await _insert_entry(session, user_id=uid, source_book_id="fresh", title="Fresh")

    repo = PostgresShelfRepository(session)
    rows = await repo.iter_unmatched(limit=10)

    assert [r.title for r in rows] == ["Fresh", "Tried"]  # NULLS FIRST


async def test_link_match_removes_entry_from_unmatched(session: AsyncSession) -> None:
    uid = await _reader(session)
    entry_id = await _insert_entry(
        session, user_id=uid, source_book_id="b1", title="Rayuela", isbn_13="9788437604572"
    )
    record_id = await _insert_record(session, title="Rayuela", isbn_13="9788437604572")
    repo = PostgresShelfRepository(session)

    assert {r.id for r in await repo.iter_unmatched(limit=10)} == {entry_id}
    await repo.link_match(entry_id, record_id, MatchVia.ISBN)

    assert await repo.iter_unmatched(limit=10) == []
    via = (
        await session.execute(
            text("SELECT matched_via FROM shelf_entries WHERE id = :id"), {"id": entry_id}
        )
    ).scalar_one()
    assert via == "isbn"


async def test_rematch_links_now_present_record_by_isbn(session: AsyncSession) -> None:
    uid = await _reader(session)
    await _insert_entry(
        session, user_id=uid, source_book_id="b1", title="Rayuela", isbn_13="9788437604572"
    )
    await _insert_record(session, title="Rayuela", isbn_13="9788437604572")

    stats = await RematchShelf(repository=PostgresShelfRepository(session)).execute()

    assert stats.linked_isbn == 1
    matched = (
        await session.execute(
            text("SELECT count(*) FROM shelf_entries WHERE matched_record_id IS NOT NULL")
        )
    ).scalar_one()
    assert matched == 1
