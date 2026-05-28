"""End-to-end HTTP integration tests for the catalog routes.

Drives the real FastAPI app via httpx.AsyncClient + ASGITransport against
a real Postgres in a testcontainer. Each test seeds a few records via the
ingest repository (so we test the read side against the exact write path
the worker uses in production).
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

from bibliohack.catalog.infrastructure.absysnet.parser import ParsedCopy, ParsedRecord
from bibliohack.catalog.infrastructure.postgres.catalog_ingest_repository import (
    PostgresCatalogIngestRepository,
)
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import get_session

pytestmark = pytest.mark.integration


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

    # Reset both the settings cache AND the engine cache so the new URL
    # propagates into the FastAPI app's session factory.
    get_settings.cache_clear()
    from bibliohack.interfaces.http.dependencies import _engine_factory_pair

    _engine_factory_pair.cache_clear()

    command.upgrade(alembic_cfg, "head")
    yield async_url


@pytest_asyncio.fixture
async def seeded_session(applied_db: str) -> AsyncIterator[AsyncSession]:
    """Yield a transactional session, then seed a couple of records,
    commit, and clean up at the end."""
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        # Always start fresh — these tests share the module-scoped DB.
        await s.execute(
            text(
                "TRUNCATE bibliographic_records, scrape_tasks, copies, "
                "branches, contributors, subjects, isbns "
                "RESTART IDENTITY CASCADE"
            )
        )
        await s.commit()

        async with factory() as ingest_session, ingest_session.begin():
            repo = PostgresCatalogIngestRepository(ingest_session)
            await repo.persist_parsed_record(
                parsed=ParsedRecord(
                    titn=1,
                    title="Cien años de soledad",
                    authors=("García Márquez, Gabriel",),
                    publisher="Editorial Sudamericana",
                    pub_year=1967,
                    document_type="Monografías",
                    language="spa",
                    record_type="a",
                    bibliographic_level="m",
                ),
                copies=[
                    ParsedCopy(branch_code="HU01", branch_name="Biblioteca Provincial de Huelva"),
                    ParsedCopy(branch_code="SE01", branch_name="Biblioteca Provincial de Sevilla"),
                ],
                source_url="https://example.test/?TITN=1",
                source_hash=b"\x01" * 32,
            )
            await repo.persist_parsed_record(
                parsed=ParsedRecord(
                    titn=2,
                    title="El amor en los tiempos del cólera",
                    authors=("García Márquez, Gabriel",),
                    publisher="Oveja Negra",
                    pub_year=1985,
                    document_type="Monografías",
                    language="spa",
                    record_type="a",
                    bibliographic_level="m",
                ),
                copies=[
                    ParsedCopy(branch_code="HU01", branch_name="Biblioteca Provincial de Huelva"),
                ],
                source_url="https://example.test/?TITN=2",
                source_hash=b"\x02" * 32,
            )
            await repo.persist_parsed_record(
                parsed=ParsedRecord(
                    titn=3,
                    title="La sombra del viento",
                    authors=("Ruiz Zafón, Carlos",),
                    publisher="Planeta",
                    pub_year=2001,
                    document_type="Monografías",
                    language="spa",
                    record_type="a",
                    bibliographic_level="m",
                ),
                copies=[],
                source_url="https://example.test/?TITN=3",
                source_hash=b"\x03" * 32,
            )

        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def client(applied_db: str, seeded_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Build a FastAPI app + AsyncClient with `get_session` overridden to
    use a session bound to THIS test's event loop. Avoids the
    'Event loop is closed' tear-down errors that happen when a cached
    engine outlives its original loop."""
    app = create_app()

    # Per-test engine — bound to the current event loop, disposed at teardown.
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


# ───────────────────────────────────────────────────────────────
# GET /catalog/records/{titn}
# ───────────────────────────────────────────────────────────────


async def test_get_record_returns_full_payload(client: AsyncClient) -> None:
    r = await client.get("/catalog/records/1")
    assert r.status_code == 200
    body = r.json()
    assert body["titn"] == 1
    assert body["title"] == "Cien años de soledad"
    assert body["publisher"] == "Editorial Sudamericana"
    assert body["pub_year"] == 1967
    assert body["authors"] == ["García Márquez, Gabriel"]
    assert len(body["copies"]) == 2
    branch_codes = {c["branch_code"] for c in body["copies"]}
    assert branch_codes == {"HU01", "SE01"}


async def test_get_record_404_for_unknown_titn(client: AsyncClient) -> None:
    r = await client.get("/catalog/records/999999")
    assert r.status_code == 404
    assert "999999" in r.json()["detail"]


async def test_get_record_422_for_invalid_titn(client: AsyncClient) -> None:
    r = await client.get("/catalog/records/0")
    assert r.status_code == 422


async def test_get_record_with_no_copies_returns_empty_list(client: AsyncClient) -> None:
    r = await client.get("/catalog/records/3")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "La sombra del viento"
    assert body["copies"] == []


# ───────────────────────────────────────────────────────────────
# GET /catalog/search
# ───────────────────────────────────────────────────────────────


async def test_search_finds_record_by_title_word(client: AsyncClient) -> None:
    r = await client.get("/catalog/search", params={"q": "soledad"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(item["titn"] == 1 for item in body["items"])


async def test_search_ignores_accents_via_spanish_unaccent(
    client: AsyncClient,
) -> None:
    """'colera' (no accent) should still find 'cólera'."""
    r = await client.get("/catalog/search", params={"q": "colera"})
    assert r.status_code == 200
    body = r.json()
    assert any(item["titn"] == 2 for item in body["items"])


async def test_search_matches_publisher(client: AsyncClient) -> None:
    r = await client.get("/catalog/search", params={"q": "Planeta"})
    assert r.status_code == 200
    body = r.json()
    assert any(item["titn"] == 3 for item in body["items"])


async def test_search_returns_summary_shape_with_copies_count(
    client: AsyncClient,
) -> None:
    # Author search isn't yet in the FTS index (covers title / subtitle /
    # publisher / summary). Use the publisher to verify summary shape.
    r = await client.get("/catalog/search", params={"q": "Editorial Sudamericana"})
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    titn_1 = next(item for item in items if item["titn"] == 1)
    assert titn_1["copies_count"] == 2


async def test_search_paginates(client: AsyncClient) -> None:
    # 'soledad' appears in one record title — small dataset, enough to
    # exercise the limit / offset / has_more shape.
    r = await client.get("/catalog/search", params={"q": "soledad", "limit": 1, "offset": 0})
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["total"] >= 1
    assert body["limit"] == 1
    assert body["offset"] == 0


async def test_search_rejects_empty_query(client: AsyncClient) -> None:
    r = await client.get("/catalog/search", params={"q": ""})
    # Pydantic field validator enforces min_length=1
    assert r.status_code == 422


async def test_search_caps_limit(client: AsyncClient) -> None:
    """Passing limit > 100 should be rejected by the Query validator."""
    r = await client.get("/catalog/search", params={"q": "x", "limit": 500})
    assert r.status_code == 422
