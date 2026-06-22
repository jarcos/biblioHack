"""HTTP integration test for library-scoped browse (Libraries L3).

Seeds three records — each held in a different branch — plus a user who follows
one branch, then asserts /catalog/browse honours `library_scope`:
  mine     → only records held in the followed branch
  province → records held anywhere in the followed branch's province
  full     → the whole mirror
and that an anonymous request is never scoped.
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
from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository
from bibliohack.identity.interfaces.http.dependencies import get_optional_user
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import get_session, get_tx_session

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


def _record(titn: int, title: str, branch_code: str, branch_name: str) -> tuple:
    return (
        ParsedRecord(
            titn=titn,
            title=title,
            authors=("Autor, Test",),
            isbns=(),
            record_type="a",
            bibliographic_level="m",
        ),
        [ParsedCopy(branch_code=branch_code, branch_name=branch_name, raw_status="Disponible")],
    )


@pytest_asyncio.fixture
async def client(applied_db: str) -> AsyncIterator[tuple[AsyncClient, object, object]]:
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as setup, setup.begin():
        await setup.execute(
            text("TRUNCATE user_followed_branches, users, copies, bibliographic_records CASCADE")
        )

    # Three records, each held in a different branch (two of them in Almería).
    seeds = [
        _record(1, "Libro de Adra", "AL03", "Adra"),
        _record(2, "Libro de Berja", "AL04", "Berja"),
        _record(3, "Libro de Sevilla", "SE01", "Sevilla"),
    ]
    for parsed, copies in seeds:
        async with factory() as s, s.begin():
            await PostgresCatalogIngestRepository(s).persist_parsed_record(
                parsed=parsed,
                copies=copies,
                source_url=f"https://example.test/?TITN={parsed.titn}",
                source_hash=bytes([parsed.titn]) * 32,
            )
    # Set provinces (the ingest path doesn't populate them; the L0 migration does
    # in prod). Almería for AL*, Sevilla for SE*.
    async with factory() as s, s.begin():
        await s.execute(text("UPDATE branches SET province = 'Almería' WHERE code LIKE 'AL%'"))
        await s.execute(text("UPDATE branches SET province = 'Sevilla' WHERE code LIKE 'SE%'"))

    reader = User.register(
        email=Email("reader@example.com"), password_hash=PasswordHash("$argon2id$fake")
    )
    async with factory() as s, s.begin():
        await PostgresUserRepository(s).add(reader)
        # Follow only Adra (AL03).
        await s.execute(
            text(
                "INSERT INTO user_followed_branches (user_id, branch_code, position) "
                "VALUES (:uid, 'AL03', 0)"
            ),
            {"uid": str(reader.id)},
        )

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async def _override_tx_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session, session.begin():
            yield session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_tx_session] = _override_tx_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac, reader, app
    app.dependency_overrides.clear()
    await engine.dispose()


def _titles(body: dict) -> set[str]:
    return {item["title"] for item in body["items"]}


async def test_anonymous_browse_is_not_scoped(
    client: tuple[AsyncClient, object, object],
) -> None:
    ac, _, _ = client
    r = await ac.get("/catalog/browse", params={"library_scope": "mine"})
    assert r.status_code == 200
    # No session → full catalogue regardless of the requested scope.
    assert r.json()["total"] == 3


async def test_mine_scope_filters_to_followed_branch(
    client: tuple[AsyncClient, object, object],
) -> None:
    ac, reader, app = client
    app.dependency_overrides[get_optional_user] = lambda: reader
    try:
        r = await ac.get("/catalog/browse", params={"library_scope": "mine"})
    finally:
        app.dependency_overrides.pop(get_optional_user, None)
    assert r.status_code == 200
    assert _titles(r.json()) == {"Libro de Adra"}


async def test_province_scope_includes_province_peers(
    client: tuple[AsyncClient, object, object],
) -> None:
    ac, reader, app = client
    app.dependency_overrides[get_optional_user] = lambda: reader
    try:
        r = await ac.get("/catalog/browse", params={"library_scope": "province"})
    finally:
        app.dependency_overrides.pop(get_optional_user, None)
    assert r.status_code == 200
    # Adra + Berja are both in Almería; Sevilla is excluded.
    assert _titles(r.json()) == {"Libro de Adra", "Libro de Berja"}


async def test_full_scope_returns_everything(
    client: tuple[AsyncClient, object, object],
) -> None:
    ac, reader, app = client
    app.dependency_overrides[get_optional_user] = lambda: reader
    try:
        r = await ac.get("/catalog/browse", params={"library_scope": "full"})
    finally:
        app.dependency_overrides.pop(get_optional_user, None)
    assert r.status_code == 200
    assert r.json()["total"] == 3
