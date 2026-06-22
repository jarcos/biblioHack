"""HTTP integration tests for the Libraries branch API (L1).

Real FastAPI app over ASGITransport against a testcontainer Postgres: seeds a
few branches + a user, then exercises the public list and the per-user follow
get/put (including unknown-code rejection and replace semantics).
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

from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository
from bibliohack.identity.interfaces.http.dependencies import get_current_user
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import get_tx_session

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

    async with factory() as setup, setup.begin():
        await setup.execute(text("TRUNCATE user_followed_branches, users, branches CASCADE"))
        await setup.execute(
            text(
                "INSERT INTO branches (code, name, municipality, province, lat, lng, is_active) "
                "VALUES "
                "('AL03','Adra','Adra','Almería',36.7497,-3.0206,true),"
                "('AL04','Berja','Berja','Almería',36.85,-2.95,true),"
                "('SE01','Sevilla','Sevilla','Sevilla',37.3886,-5.9823,true)"
            )
        )
    reader = User.register(
        email=Email("reader@example.com"), password_hash=PasswordHash("$argon2id$fake")
    )
    async with factory() as setup, setup.begin():
        await PostgresUserRepository(setup).add(reader)

    app = create_app()

    async def _override_tx_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session, session.begin():
            yield session

    app.dependency_overrides[get_tx_session] = _override_tx_session
    app.dependency_overrides[get_current_user] = lambda: reader
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_list_branches_is_public_and_carries_geo(client: AsyncClient) -> None:
    r = await client.get("/api/branches")
    assert r.status_code == 200
    branches = r.json()["branches"]
    assert {b["code"] for b in branches} == {"AL03", "AL04", "SE01"}
    adra = next(b for b in branches if b["code"] == "AL03")
    assert adra["municipality"] == "Adra"
    assert adra["province"] == "Almería"
    assert adra["lat"] == pytest.approx(36.7497)


async def test_follow_roundtrip_and_replace(client: AsyncClient) -> None:
    # Initially follows nothing.
    assert (await client.get("/api/me/branches")).json()["codes"] == []

    # Follow two, order preserved.
    r = await client.put("/api/me/branches", json={"codes": ["SE01", "AL03"]})
    assert r.status_code == 200
    assert r.json()["codes"] == ["SE01", "AL03"]
    assert (await client.get("/api/me/branches")).json()["codes"] == ["SE01", "AL03"]

    # PUT replaces (not appends).
    r = await client.put("/api/me/branches", json={"codes": ["AL04"]})
    assert r.json()["codes"] == ["AL04"]


async def test_unknown_branch_code_is_rejected(client: AsyncClient) -> None:
    r = await client.put("/api/me/branches", json={"codes": ["AL03", "ZZ99"]})
    assert r.status_code == 422
    assert "ZZ99" in r.json()["detail"]
    # The bad request didn't change the follow set.
    assert (await client.get("/api/me/branches")).json()["codes"] == []
