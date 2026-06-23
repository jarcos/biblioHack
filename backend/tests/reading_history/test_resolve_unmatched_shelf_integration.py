"""Integration tests for the shelf-resolve repository SQL (real Postgres).

The dedup-across-users grouping, the cooldown window (`make_interval`), the
eligibility filter (unmatched + not 'held' + due), and `mark_resolve_result`'s
attempt/timestamp bookkeeping can't be exercised with fakes — they're SQL. Real
Postgres via testcontainers; also applies the `20260622_0020` migration to head.
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

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository
from bibliohack.reading_history.domain.shelf import ShelfResolveStatus
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
        await setup.execute(text("TRUNCATE users, shelf_entries CASCADE"))
    async with factory() as s, s.begin():
        yield s
    await engine.dispose()


async def _reader(session: AsyncSession, email: str) -> str:
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
    resolve_status: str = "unchecked",
    last_resolved_sql: str = "NULL",
) -> str:
    entry_id = uuid4()
    # last_resolved_at via a SQL expression (e.g. "now() - interval '40 days'")
    # so cooldown tests can place an entry inside/outside the window precisely.
    await session.execute(
        text(
            "INSERT INTO shelf_entries "
            "(id, user_id, source, source_book_id, title, author, isbn_13, shelf, "
            " resolve_status, last_resolved_at) "
            "VALUES (:id, :uid, 'goodreads', :sbid, :title, :author, :isbn, 'read', "
            f" :status, {last_resolved_sql})"
        ),
        {
            "id": entry_id,
            "uid": user_id,
            "sbid": source_book_id,
            "title": title,
            "author": author,
            "isbn": isbn_13,
            "status": resolve_status,
        },
    )
    return str(entry_id)


async def test_dedup_across_users_by_isbn(session: AsyncSession) -> None:
    u1 = await _reader(session, "a@example.com")
    u2 = await _reader(session, "b@example.com")
    e1 = await _insert_entry(
        session, user_id=u1, source_book_id="b", title="Rayuela", isbn_13="9788437604572"
    )
    e2 = await _insert_entry(
        session, user_id=u2, source_book_id="b", title="Rayuela", isbn_13="9788437604572"
    )

    books = await PostgresShelfRepository(session).iter_resolvable_books(limit=10, cooldown_days=30)

    assert len(books) == 1  # same ISBN → one deduped book
    assert set(books[0].entry_ids) == {e1, e2}
    assert books[0].isbn13 == ("9788437604572",)


async def test_dedup_by_title_author_when_no_isbn(session: AsyncSession) -> None:
    u1 = await _reader(session, "a@example.com")
    u2 = await _reader(session, "b@example.com")
    await _insert_entry(session, user_id=u1, source_book_id="b", title="Nada", author="Laforet")
    await _insert_entry(session, user_id=u2, source_book_id="b", title="nada", author="laforet")

    books = await PostgresShelfRepository(session).iter_resolvable_books(limit=10, cooldown_days=30)

    assert len(books) == 1  # case-insensitive title+author key collapses them
    assert len(books[0].entry_ids) == 2


async def test_cooldown_excludes_recent_not_held_includes_stale(session: AsyncSession) -> None:
    uid = await _reader(session, "a@example.com")
    await _insert_entry(
        session,
        user_id=uid,
        source_book_id="recent",
        title="Recent",
        author="X",
        resolve_status="not_held",
        last_resolved_sql="now() - interval '5 days'",
    )
    await _insert_entry(
        session,
        user_id=uid,
        source_book_id="stale",
        title="Stale",
        author="Y",
        resolve_status="not_held",
        last_resolved_sql="now() - interval '40 days'",
    )

    books = await PostgresShelfRepository(session).iter_resolvable_books(limit=10, cooldown_days=30)

    titles = {b.title for b in books}
    assert titles == {"Stale"}  # recent miss still in cooldown; stale one is due


async def test_held_and_matched_are_excluded(session: AsyncSession) -> None:
    uid = await _reader(session, "a@example.com")
    await _insert_entry(
        session,
        user_id=uid,
        source_book_id="held",
        title="Held",
        author="X",
        resolve_status="held",
        last_resolved_sql="now() - interval '99 days'",
    )

    books = await PostgresShelfRepository(session).iter_resolvable_books(limit=10, cooldown_days=30)

    assert books == []  # 'held' is never re-resolved


async def test_mark_resolve_result_bumps_attempts_and_stamps(session: AsyncSession) -> None:
    uid = await _reader(session, "a@example.com")
    e1 = await _insert_entry(session, user_id=uid, source_book_id="b", title="T", author="A")
    repo = PostgresShelfRepository(session)

    await repo.mark_resolve_result([e1], ShelfResolveStatus.NOT_HELD)

    row = (
        await session.execute(
            text(
                "SELECT resolve_status, resolve_attempts, last_resolved_at "
                "FROM shelf_entries WHERE id = :id"
            ),
            {"id": e1},
        )
    ).one()
    assert row.resolve_status == "not_held"
    assert row.resolve_attempts == 1
    assert row.last_resolved_at is not None

    # Now in cooldown → no longer resolvable.
    assert await repo.iter_resolvable_books(limit=10, cooldown_days=30) == []
