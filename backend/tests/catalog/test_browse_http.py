"""HTTP integration tests for the catalogue navigator (browse + authors).

Same harness as test_catalog_http: real FastAPI app over ASGITransport
against a testcontainer Postgres, seeded through the production ingest path
so genre derivation runs exactly as it does on the crawler.
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


_RECORDS = [
    # (titn, title, authors, pub_year, language, classification, signature)
    (
        1,
        "Cien años de soledad",
        ("García Márquez, Gabriel",),
        1967,
        "spa",
        "821.134.2-31",
        "N GAR cie",
    ),
    (
        2,
        "El amor en los tiempos del cólera",
        ("García Márquez, Gabriel",),
        1985,
        "spa",
        "821.134.2-31",
        "N GAR amo",
    ),
    (
        3,
        "Romancero gitano",
        ("García Lorca, Federico",),
        1928,
        "spa",
        '821.134.2-1"19"',
        "P GAR rom",
    ),
    (
        4,
        "La casa de Bernarda Alba",
        ("García Lorca, Federico",),
        1936,
        "spa",
        "821.134.2-2",
        "T GAR cas",
    ),
    (5, "Watchmen", ("Moore, Alan",), 1987, "eng", "741.5", "C MOO wat"),
    (6, "Historia de España", ("Vilar, Pierre",), 1978, "spa", "94(460)", None),
]


@pytest_asyncio.fixture(scope="module")
async def seeded(applied_db: str) -> AsyncIterator[str]:
    """Seed the module's six records once, through the real ingest path."""
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(
            text(
                "TRUNCATE bibliographic_records, scrape_tasks, copies, "
                "branches, contributors, subjects, isbns "
                "RESTART IDENTITY CASCADE"
            )
        )
        await s.commit()
    async with factory() as ingest, ingest.begin():
        repo = PostgresCatalogIngestRepository(ingest)
        for titn, title, authors, pub_year, language, classification, signature in _RECORDS:
            await repo.persist_parsed_record(
                parsed=ParsedRecord(
                    titn=titn,
                    title=title,
                    authors=authors,
                    publisher="Editorial",
                    pub_year=pub_year,
                    language=language,
                    classification=classification,
                    record_type="a",
                    bibliographic_level="m",
                ),
                copies=[
                    ParsedCopy(
                        branch_code="HU01",
                        branch_name="Biblioteca Provincial de Huelva",
                        signature=signature,
                        barcode=f"BC{titn}",
                    )
                ],
                source_url=f"https://example.test/?TITN={titn}",
                source_hash=bytes([titn]) * 32,
            )
    # One record gets an 'available' snapshot so the availability filter bites.
    async with factory() as s:
        await s.execute(
            text(
                "INSERT INTO availability_snapshots (copy_id, observed_at, status) "
                "SELECT c.id, now(), 'available' FROM copies c "
                "JOIN bibliographic_records r ON r.id = c.record_id WHERE r.titn = 1"
            )
        )
        await s.commit()
    yield applied_db
    await engine.dispose()


@pytest_asyncio.fixture
async def client(seeded: str) -> AsyncIterator[AsyncClient]:
    app = create_app()
    engine = create_async_engine(seeded, future=True)
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


async def test_browse_unfiltered_covers_the_whole_mirror(client: AsyncClient) -> None:
    r = await client.get("/catalog/browse")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 6
    # Default sort is newest-first.
    years = [item["pub_year"] for item in body["items"]]
    assert years == sorted(years, reverse=True)
    # Facets present, with the ingest-derived genres counted.
    genre_counts = {f["value"]: f["count"] for f in body["facets"]["genre"]}
    assert genre_counts["narrative"] == 2
    assert genre_counts["poetry"] == 1
    assert genre_counts["drama"] == 1
    assert genre_counts["comic"] == 1
    assert genre_counts["unknown"] == 1  # the history book
    language_counts = {f["value"]: f["count"] for f in body["facets"]["language"]}
    assert language_counts == {"spa": 5, "eng": 1}


async def test_browse_filters_compose(client: AsyncClient) -> None:
    r = await client.get(
        "/catalog/browse",
        params={"genre": "narrative", "language": "spa", "year_from": 1980},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["titn"] == 2
    # Facet contract: the genre facet ignores the genre filter itself, so
    # poetry/drama stay visible (scoped to spa + year_from).
    genre_counts = {f["value"]: f["count"] for f in body["facets"]["genre"]}
    assert genre_counts["narrative"] == 1
    assert "poetry" not in genre_counts  # 1928 < year_from


async def test_browse_by_author_and_title_sort(client: AsyncClient) -> None:
    r = await client.get(
        "/catalog/browse",
        params={"author": "García Lorca, Federico", "sort": "title"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    titles = [item["title"] for item in body["items"]]
    assert titles == sorted(titles)


async def test_browse_available_only(client: AsyncClient) -> None:
    r = await client.get("/catalog/browse", params={"available": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["titn"] == 1
    assert body["items"][0]["available_count"] == 1


async def test_browse_rejects_unknown_genre(client: AsyncClient) -> None:
    r = await client.get("/catalog/browse", params={"genre": "telenovela"})
    assert r.status_code == 422


async def test_authors_directory_and_search(client: AsyncClient) -> None:
    r = await client.get("/catalog/authors")
    assert r.status_code == 200
    items = r.json()["items"]
    by_name = {a["name"]: a["records"] for a in items}
    assert by_name["García Márquez, Gabriel"] == 2
    assert by_name["García Lorca, Federico"] == 2
    # Most-represented first; search narrows by substring, case-insensitively.
    r = await client.get("/catalog/authors", params={"q": "lorca"})
    names = [a["name"] for a in r.json()["items"]]
    assert names == ["García Lorca, Federico"]
