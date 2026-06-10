"""End-to-end HTTP test for GET /shelf.

Seeds a catalogue record + imports two shelf entries (one ISBN-matched, one
unmatched) through the real repositories, then drives the FastAPI app and
asserts the grouped, enriched response shape.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

from bibliohack.catalog.infrastructure.absysnet.parser import ParsedRecord
from bibliohack.catalog.infrastructure.postgres.catalog_ingest_repository import (
    PostgresCatalogIngestRepository,
)
from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository
from bibliohack.identity.interfaces.http.dependencies import get_current_user
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import get_session
from bibliohack.reading_history.application.use_cases.import_shelf import ImportShelf
from bibliohack.reading_history.domain.shelf import Shelf
from bibliohack.reading_history.infrastructure.goodreads.csv_parser import GoodreadsRow
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
    from bibliohack.interfaces.http.dependencies import _engine_factory_pair

    _engine_factory_pair.cache_clear()
    command.upgrade(alembic_cfg, "head")
    yield async_url


@pytest_asyncio.fixture
async def client(applied_db: str) -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Seed a catalogue record, then import two shelf entries (one matches by
    # ISBN, one stays unmatched).
    from sqlalchemy import text

    async with factory() as setup, setup.begin():
        await setup.execute(text("TRUNCATE bibliographic_records, shelf_entries, users CASCADE"))
    reader = User.register(
        email=Email("reader@example.com"), password_hash=PasswordHash("$argon2id$fake")
    )
    async with factory() as setup, setup.begin():
        await PostgresUserRepository(setup).add(reader)
    async with factory() as setup, setup.begin():
        await PostgresCatalogIngestRepository(setup).persist_parsed_record(
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
    async with factory() as setup, setup.begin():
        await ImportShelf(repository=PostgresShelfRepository(setup)).execute(
            [
                GoodreadsRow(
                    source_book_id="m1",
                    title="Cien años de soledad",
                    author="Gabriel García Márquez",
                    isbn_13="9788497592208",
                    shelf=Shelf.READ,
                    rating=5,
                    review=None,
                    date_read=None,
                    date_added=None,
                ),
                GoodreadsRow(
                    source_book_id="u1",
                    title="Un libro que no está en el catálogo",
                    author="Autor Desconocido",
                    isbn_13=None,
                    shelf=Shelf.TO_READ,
                    rating=None,
                    review=None,
                    date_read=None,
                    date_added=None,
                ),
            ],
            user_id=str(reader.id),
        )

    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    # Authenticate as the seeded reader without Redis/cookies: the shelf
    # route depends on get_current_user, which we override wholesale.
    app.dependency_overrides[get_current_user] = lambda: reader
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_shelf_groups_and_enriches(client: AsyncClient) -> None:
    r = await client.get("/api/shelf")
    assert r.status_code == 200
    body = r.json()

    assert body["counts"]["total"] == 2
    assert body["counts"]["matched"] == 1
    assert body["counts"]["read"] == 1
    assert body["counts"]["to_read"] == 1
    assert body["counts"]["currently_reading"] == 0

    # The matched 'read' book carries its catalogue projection (titn + cover state).
    read = body["read"]
    assert len(read) == 1
    matched = read[0]
    assert matched["matched_via"] == "isbn"
    assert matched["rating"] == 5
    assert matched["match"] is not None
    assert matched["match"]["titn"] == 1
    assert "cover" in matched["match"]

    # The unmatched 'to-read' book still appears, without a catalogue match.
    to_read = body["to_read"]
    assert len(to_read) == 1
    assert to_read[0]["match"] is None
    assert to_read[0]["matched_via"] == "none"


async def test_shelf_requires_authentication(applied_db: str) -> None:
    """Without a session cookie the shelf is a 401 — never another user's data."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        r = await ac.get("/api/shelf")
    assert r.status_code == 401
