"""End-to-end HTTP integration tests for the catalog routes.

Drives the real FastAPI app via httpx.AsyncClient + ASGITransport against
a real Postgres in a testcontainer. Each test seeds a few records via the
ingest repository (so we test the read side against the exact write path
the worker uses in production).
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
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

from bibliohack.catalog.application.dto import RewrittenQuery
from bibliohack.catalog.infrastructure.absysnet.parser import ParsedCopy, ParsedRecord
from bibliohack.catalog.infrastructure.postgres.catalog_ingest_repository import (
    PostgresCatalogIngestRepository,
)
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import (
    get_embedder,
    get_query_rewriter,
    get_session,
)

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
    r = await client.get("/catalog/search", params={"q": "Editorial Sudamericana"})
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    titn_1 = next(item for item in items if item["titn"] == 1)
    assert titn_1["copies_count"] == 2


async def test_search_finds_record_by_author_surname(client: AsyncClient) -> None:
    """Author names are folded into the FTS column via `authors_text`."""
    r = await client.get("/catalog/search", params={"q": "Márquez"})
    assert r.status_code == 200
    body = r.json()
    titns = {item["titn"] for item in body["items"]}
    assert {1, 2}.issubset(titns)


async def test_search_finds_author_accent_insensitive(client: AsyncClient) -> None:
    """`spanish_unaccent` should let 'Garcia Marquez' match 'García Márquez'."""
    r = await client.get("/catalog/search", params={"q": "Garcia Marquez"})
    assert r.status_code == 200
    body = r.json()
    titns = {item["titn"] for item in body["items"]}
    assert {1, 2}.issubset(titns)


async def test_search_by_author_returns_only_their_records(client: AsyncClient) -> None:
    """An author query must not bleed in records by other authors."""
    r = await client.get("/catalog/search", params={"q": "Zafón"})
    assert r.status_code == 200
    body = r.json()
    titns = {item["titn"] for item in body["items"]}
    assert 3 in titns
    assert 1 not in titns
    assert 2 not in titns


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


# ───────────────────────────────────────────────────────────────
# Query rewriting (§8.3.1) — rewrite=true routes structured intent to browse
# ───────────────────────────────────────────────────────────────


class _StubRewriter:
    """Rewrites one known phrase to a structured intent; passes everything else."""

    def __init__(self, mapping: dict[str, RewrittenQuery]) -> None:
        self._mapping = mapping

    async def rewrite(self, query: str) -> RewrittenQuery | None:
        return self._mapping.get(query)


@pytest_asyncio.fixture
async def rewrite_client(
    applied_db: str, seeded_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    """Like `client`, but with a stub rewriter that maps a natural-language
    query for García Márquez to author + newest-first."""
    app = create_app()
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_query_rewriter] = lambda: _StubRewriter(
        {
            "lo último de García Márquez": RewrittenQuery(
                author="García Márquez, Gabriel", sort="newest"
            ),
            "lo último de Nadie Existente": RewrittenQuery(author="Nadie Existente"),
        }
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


async def test_rewrite_routes_to_browse_and_echoes_intent(rewrite_client: AsyncClient) -> None:
    r = await rewrite_client.get("/catalog/search", params={"q": "lo último de García Márquez"})
    assert r.status_code == 200
    body = r.json()
    # Browse on author=García Márquez, newest-first → only their two records, 1985 before 1967.
    titns = [item["titn"] for item in body["items"]]
    assert titns == [2, 1]
    assert body["rewritten"] == {
        "author": "García Márquez, Gabriel",
        "year_from": None,
        "year_to": None,
        "sort": "newest",
    }


async def test_rewrite_false_forces_literal_search(rewrite_client: AsyncClient) -> None:
    r = await rewrite_client.get(
        "/catalog/search",
        params={"q": "lo último de García Márquez", "rewrite": "false"},
    )
    assert r.status_code == 200
    body = r.json()
    # No rewrite applied → literal FTS, which won't match this phrase as a whole.
    assert body["rewritten"] is None


async def test_rewrite_zero_results_falls_back_to_literal(rewrite_client: AsyncClient) -> None:
    """A mis-parsed author that browse can't satisfy degrades to literal search,
    never an empty page courtesy of the rewrite."""
    r = await rewrite_client.get("/catalog/search", params={"q": "lo último de Nadie Existente"})
    assert r.status_code == 200
    body = r.json()
    assert body["rewritten"] is None  # browse found nothing → rewrite abandoned


# ───────────────────────────────────────────────────────────────
# Availability read-side (latest snapshot per copy)
# ───────────────────────────────────────────────────────────────


# ───────────────────────────────────────────────────────────────
# Semantic search + "más como este" (pgvector KNN)
# ───────────────────────────────────────────────────────────────

_DIM = 1024


def _vec(*head: float) -> str:
    """A 1024-d pgvector literal from a short head (rest zero-padded)."""
    values = list(head) + [0.0] * (_DIM - len(head))
    return "[" + ",".join(str(v) for v in values) + "]"


class _FakeEmbedder:
    """Stands in for the HF embedder: returns a fixed query vector."""

    def __init__(self, query_vector: str) -> None:
        self._literal = query_vector

    @property
    def dimensions(self) -> int:
        return _DIM

    def embed_documents(self, texts: object) -> list[list[float]]:  # pragma: no cover
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        inner = self._literal.strip("[]")
        return [float(x) for x in inner.split(",")]


@pytest_asyncio.fixture
async def embedded(seeded_session: AsyncSession) -> AsyncIterator[None]:
    """Give the three seeded records distinct unit-ish embeddings.

    record 1 ≈ axis 0; record 2 ≈ close to record 1 (cos 0.8); record 3 ≈ axis 2
    (far from both). This lets KNN ordering be asserted deterministically.
    """
    await seeded_session.execute(
        text("UPDATE bibliographic_records SET embedding = CAST(:v AS vector) WHERE titn = 1"),
        {"v": _vec(1.0, 0.0, 0.0)},
    )
    await seeded_session.execute(
        text("UPDATE bibliographic_records SET embedding = CAST(:v AS vector) WHERE titn = 2"),
        {"v": _vec(0.8, 0.6, 0.0)},
    )
    await seeded_session.execute(
        text("UPDATE bibliographic_records SET embedding = CAST(:v AS vector) WHERE titn = 3"),
        {"v": _vec(0.0, 0.0, 1.0)},
    )
    await seeded_session.commit()
    yield


@pytest_asyncio.fixture
async def semantic_client(applied_db: str, embedded: None) -> AsyncIterator[AsyncClient]:
    """Like `client`, but also overrides the embedder with a fake whose query
    vector points at axis 0 (closest to record 1, then 2, then 3)."""
    app = create_app()
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_embedder] = lambda: _FakeEmbedder(_vec(1.0, 0.0, 0.0))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


async def test_semantic_search_ranks_by_cosine_distance(semantic_client: AsyncClient) -> None:
    r = await semantic_client.get(
        "/catalog/search", params={"q": "novela de amor", "mode": "semantic", "scope": "all"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "semantic"
    titns = [item["titn"] for item in body["items"]]
    # Query points at axis 0: record 1 (exact) before 2 (near) before 3 (far).
    assert titns[:3] == [1, 2, 3]


async def test_semantic_search_falls_back_to_keyword_without_embedder(
    client: AsyncClient,
) -> None:
    """The default `client` has no embedder override → get_embedder returns None
    (no token in the test env), so a semantic request degrades to keyword."""
    r = await client.get("/catalog/search", params={"q": "soledad", "mode": "semantic"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "keyword"
    assert any(item["titn"] == 1 for item in body["items"])


async def test_similar_returns_nearest_neighbours(semantic_client: AsyncClient) -> None:
    # Anchor = record 1 (axis 0). Nearest is record 2 (cos 0.8), then record 3.
    r = await semantic_client.get("/catalog/records/1/similar")
    assert r.status_code == 200
    body = r.json()
    assert body["titn"] == 1
    titns = [item["titn"] for item in body["items"]]
    assert 1 not in titns  # the anchor itself is excluded
    assert titns[0] == 2  # closest neighbour first


async def test_similar_empty_for_unembedded_record(client: AsyncClient) -> None:
    """The default `client` fixture seeds records WITHOUT embeddings, so similar
    returns an empty strip rather than erroring."""
    r = await client.get("/catalog/records/1/similar")
    assert r.status_code == 200
    assert r.json() == {"titn": 1, "items": []}


async def test_similar_422_for_invalid_titn(client: AsyncClient) -> None:
    r = await client.get("/catalog/records/0/similar")
    assert r.status_code == 422


async def test_read_side_reflects_latest_availability(
    client: AsyncClient, seeded_session: AsyncSession
) -> None:
    """The record detail exposes each copy's *latest* status, and search
    reports how many copies are available right now.

    Record 1 has two copies (HU01, SE01). We give HU01 a newer 'loaned' over
    an older 'available' (latest must win) and SE01 a single 'available'."""
    copy_rows = (
        await seeded_session.execute(
            text(
                "SELECT c.id, c.branch_code FROM copies c "
                "JOIN bibliographic_records r ON r.id = c.record_id "
                "WHERE r.titn = 1 ORDER BY c.branch_code"
            )
        )
    ).all()
    by_branch = {branch_code: copy_id for copy_id, branch_code in copy_rows}
    t0 = datetime(2026, 5, 30, 8, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)
    await seeded_session.execute(
        text(
            "INSERT INTO availability_snapshots (copy_id, observed_at, status) VALUES "
            "(:hu, :t0, 'available'), (:hu, :t1, 'loaned'), (:se, :t1, 'available')"
        ),
        {"hu": by_branch["HU01"], "se": by_branch["SE01"], "t0": t0, "t1": t1},
    )
    await seeded_session.commit()

    # Detail: HU01 resolves to the newer 'loaned'; SE01 to 'available'.
    detail = await client.get("/catalog/records/1")
    assert detail.status_code == 200
    copies = {c["branch_code"]: c for c in detail.json()["copies"]}
    assert copies["HU01"]["status"] == "loaned"
    assert copies["SE01"]["status"] == "available"

    # Search: exactly one of record 1's copies is on the shelf right now.
    found = await client.get("/catalog/search", params={"q": "soledad"})
    assert found.status_code == 200
    item = next(i for i in found.json()["items"] if i["titn"] == 1)
    assert item["available_count"] == 1
