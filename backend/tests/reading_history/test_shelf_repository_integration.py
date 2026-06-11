"""Integration tests for `PostgresShelfRepository`.

Runs against a real Postgres (testcontainers, same image as prod) with Alembic
migrations applied, so the Postgres-specific bits are actually exercised: the
ISBN join, the pg_trgm `similarity()` title/author fallback, and the
`ON CONFLICT … DO UPDATE` upsert with `xmax = 0` insert detection.

Catalogue rows are seeded through the real ingest repository so the schema and
ISBN normalization match production exactly.

Marked `integration` so quick CI runs can skip them; full CI applies them.
"""

from __future__ import annotations

import os
from datetime import date
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

from bibliohack.catalog.infrastructure.absysnet.parser import ParsedRecord
from bibliohack.catalog.infrastructure.postgres.catalog_ingest_repository import (
    PostgresCatalogIngestRepository,
)
from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository
from bibliohack.reading_history.application.ports import ShelfEntryData
from bibliohack.reading_history.domain.shelf import MatchVia, Shelf
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
async def seeded(applied_db: str) -> AsyncIterator[AsyncSession]:
    """A session with two catalogue records seeded (committed), rolled back at end."""
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as setup, setup.begin():
        from sqlalchemy import text

        await setup.execute(text("TRUNCATE bibliographic_records, shelf_entries, users CASCADE"))

    async with factory() as setup, setup.begin():
        for email in ("reader-a@example.com", "reader-b@example.com"):
            await PostgresUserRepository(setup).add(
                User.register(email=Email(email), password_hash=PasswordHash("$argon2id$fake"))
            )

    async with factory() as setup, setup.begin():
        ingest = PostgresCatalogIngestRepository(setup)
        await ingest.persist_parsed_record(
            parsed=ParsedRecord(
                titn=1,
                title="Cien años de soledad",
                authors=("García Márquez, Gabriel",),
                isbns=("9788497592208",),
                record_type="a",
                bibliographic_level="m",
            ),
            copies=[],
            source_url="https://example.test/?TITN=1",
            source_hash=b"\x01" * 32,
        )

    async with factory() as s:
        yield s
    await engine.dispose()


async def _user_id(session: AsyncSession, email: str = "reader-a@example.com") -> str:
    user = await PostgresUserRepository(session).get_by_email(email)
    assert user is not None
    return str(user.id)


def _entry(**overrides: object) -> ShelfEntryData:
    base: dict[str, object] = {
        "user_id": "set-by-test",
        "source": "goodreads",
        "source_book_id": "g1",
        "title": "Cien años de soledad",
        "author": "Gabriel García Márquez",
        "isbn_13": None,
        "shelf": Shelf.READ,
        "rating": 5,
        "review": None,
        "date_read": date(2024, 1, 2),
        "date_added": None,
        "matched_record_id": None,
        "matched_via": MatchVia.NONE,
    }
    base.update(overrides)
    return ShelfEntryData(**base)  # type: ignore[arg-type]


async def test_match_isbn13_hits_the_catalogue(seeded: AsyncSession) -> None:
    repo = PostgresShelfRepository(seeded)
    record_id = await repo.match_isbn13("9788497592208")
    assert record_id is not None
    assert await repo.match_isbn13("9780000000000") is None


async def test_match_title_author_via_trigram(seeded: AsyncSession) -> None:
    repo = PostgresShelfRepository(seeded)
    # Author word order differs from the catalogue's "Surname, First" — trigrams
    # still resolve it.
    record_id = await repo.match_title_author("Cien años de soledad", "Gabriel García Márquez")
    assert record_id is not None
    # A clearly different title must not match.
    assert await repo.match_title_author("Manual de fontanería industrial", "Anon") is None


async def test_upsert_is_idempotent_per_user_and_reports_insert_vs_update(
    seeded: AsyncSession,
) -> None:
    repo = PostgresShelfRepository(seeded)
    isbn_match = await repo.match_isbn13("9788497592208")
    uid = await _user_id(seeded)

    first = await repo.upsert_entry(
        _entry(
            user_id=uid,
            isbn_13="9788497592208",
            matched_record_id=isbn_match,
            matched_via=MatchVia.ISBN,
            shelf=Shelf.TO_READ,
        )
    )
    assert first is True  # inserted

    # A later Goodreads re-import: the same book has moved to-read → read
    # and gained a rating. The re-import must update in place, not duplicate.
    second = await repo.upsert_entry(
        _entry(
            user_id=uid,
            isbn_13="9788497592208",
            matched_record_id=isbn_match,
            matched_via=MatchVia.ISBN,
            shelf=Shelf.READ,
            rating=3,
        )
    )
    assert second is False  # updated in place, not duplicated

    from sqlalchemy import text

    count = (
        await seeded.execute(text("SELECT count(*) FROM shelf_entries WHERE source_book_id = 'g1'"))
    ).scalar_one()
    shelf, rating = (
        await seeded.execute(
            text("SELECT shelf, rating FROM shelf_entries WHERE source_book_id = 'g1'")
        )
    ).one()
    assert count == 1
    assert shelf == "read"  # the shelf transition took
    assert rating == 3  # the rating update took


async def test_same_book_lives_independently_on_each_users_shelf(seeded: AsyncSession) -> None:
    """The unique key is per-user: two readers can log the same Goodreads book."""
    repo = PostgresShelfRepository(seeded)
    uid_a = await _user_id(seeded, "reader-a@example.com")
    uid_b = await _user_id(seeded, "reader-b@example.com")

    assert await repo.upsert_entry(_entry(user_id=uid_a, rating=5)) is True
    assert await repo.upsert_entry(_entry(user_id=uid_b, rating=2)) is True  # insert, not update

    from bibliohack.reading_history.infrastructure.postgres.shelf_read_repository import (
        PostgresShelfReadRepository,
    )

    read = PostgresShelfReadRepository(seeded)
    entries_a = await read.list_entries(uid_a)
    entries_b = await read.list_entries(uid_b)
    assert [e.rating for e in entries_a] == [5]  # A never sees B's copy
    assert [e.rating for e in entries_b] == [2]
