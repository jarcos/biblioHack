"""Cross-user isolation + GDPR account endpoints, over real HTTP + Postgres.

The whole identity milestone's security claim in one suite: two users go
through the real register→verify→login flow (real Postgres repositories;
only the hasher/session-store/mailer/captcha/rate-limiter edges are faked),
then we prove that neither can see the other's shelf or import jobs, that
the export contains exactly the caller's data, and that account deletion
erases the user, cascades to their data, kills their session — and leaves
the other user untouched.
"""

from __future__ import annotations

import os
import re
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

    from fastapi import FastAPI

from bibliohack.identity.interfaces.http.dependencies import (
    get_captcha_verifier,
    get_mailer,
    get_password_hasher,
    get_session_store,
)
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import _engine_factory_pair, get_rate_limiter
from bibliohack.reading_history.application.ports import ShelfEntryData
from bibliohack.reading_history.domain.shelf import MatchVia, Shelf
from bibliohack.reading_history.infrastructure.postgres.import_job_repository import (
    PostgresImportJobRepository,
)
from bibliohack.reading_history.infrastructure.postgres.shelf_repository import (
    PostgresShelfRepository,
)
from bibliohack.shared.infrastructure.ratelimit import RedisRateLimiter
from tests.identity.fakes import (
    AlwaysPassCaptcha,
    FakePasswordHasher,
    InMemorySessionStore,
    RecordingMailer,
)
from tests.shared.test_rate_limit import FakeRedis

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
async def harness(applied_db: str) -> AsyncIterator[tuple[FastAPI, RecordingMailer, str]]:
    engine = create_async_engine(applied_db, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup, setup.begin():
        await setup.execute(
            text("TRUNCATE users, shelf_entries, import_jobs, recommendations CASCADE")
        )
    mailer = RecordingMailer()
    app = create_app()
    app.dependency_overrides[get_password_hasher] = FakePasswordHasher
    app.dependency_overrides[get_mailer] = lambda: mailer
    app.dependency_overrides[get_captcha_verifier] = AlwaysPassCaptcha
    sessions = InMemorySessionStore()
    app.dependency_overrides[get_session_store] = lambda: sessions
    app.dependency_overrides[get_rate_limiter] = lambda: RedisRateLimiter(FakeRedis())  # type: ignore[arg-type]
    yield app, mailer, applied_db
    app.dependency_overrides.clear()
    # Unlike the other HTTP suites, this one runs the app's REAL session
    # dependencies, so the app built an engine via the cached factory pair.
    # Dispose it on the loop it was created on (this test's loop) and drop
    # the cache entry — otherwise its pooled asyncpg sockets get GC'd later
    # and `filterwarnings = error` turns the ResourceWarning into a flaky
    # ERROR pinned on whichever test happens to run next.
    from bibliohack.shared.infrastructure.settings import get_settings

    app_engine, _ = _engine_factory_pair(get_settings())
    await app_engine.dispose()
    _engine_factory_pair.cache_clear()
    await engine.dispose()


async def _signed_in_client(app: FastAPI, mailer: RecordingMailer, email: str) -> AsyncClient:
    """Register → verify → login one user; returns a client carrying their cookie."""
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    register = await client.post(
        "/api/auth/register", json={"email": email, "password": "long-enough-pass"}
    )
    assert register.status_code == 201, register.text
    token_match = re.search(r"token=([\w.~-]+)", mailer.sent[-1][2])
    assert token_match is not None
    assert (
        await client.post("/api/auth/verify", json={"token": token_match.group(1)})
    ).status_code == 204
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "long-enough-pass"}
    )
    assert login.status_code == 200, login.text
    return client


def _entry(user_id: str, book_id: str, title: str) -> ShelfEntryData:
    return ShelfEntryData(
        user_id=user_id,
        source="goodreads",
        source_book_id=book_id,
        title=title,
        author=None,
        isbn_13=None,
        shelf=Shelf.READ,
        rating=5,
        review="mi reseña",
        date_read=None,
        date_added=None,
        matched_record_id=None,
        matched_via=MatchVia.NONE,
    )


async def test_users_cannot_see_each_other_and_deletion_is_complete(
    harness: tuple[FastAPI, RecordingMailer, str],
) -> None:
    app, mailer, db_url = harness
    alice = await _signed_in_client(app, mailer, "alice@example.com")
    bob = await _signed_in_client(app, mailer, "bob@example.com")

    alice_id = (await alice.get("/api/auth/me")).json()["id"]
    bob_id = (await bob.get("/api/auth/me")).json()["id"]

    # Seed one shelf book each + an import job for Bob, via the real repos.
    engine = create_async_engine(db_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await PostgresShelfRepository(session).upsert_entry(
            _entry(alice_id, "a1", "El libro de Alice")
        )
        await PostgresShelfRepository(session).upsert_entry(_entry(bob_id, "b1", "El libro de Bob"))
        bob_job = await PostgresImportJobRepository(session).create(
            user_id=bob_id, filename="bob.csv", csv_content="Book Id,Title\n1,X\n"
        )

    # ── Isolation: shelves ────────────────────────────────────
    alice_shelf = (await alice.get("/api/shelf")).json()
    titles = [entry["title"] for entry in alice_shelf["read"]]
    assert titles == ["El libro de Alice"]  # Bob's book is invisible

    # ── Isolation: import jobs ────────────────────────────────
    assert (await alice.get(f"/api/shelf/import/{bob_job}")).status_code == 404
    assert (await bob.get(f"/api/shelf/import/{bob_job}")).status_code == 200

    # ── Export: exactly the caller's data ─────────────────────
    export_response = await alice.get("/api/account/export")
    assert export_response.status_code == 200
    assert "attachment" in export_response.headers["content-disposition"]
    export = export_response.json()
    assert export["account"]["email"] == "alice@example.com"
    assert [book["title"] for book in export["shelf"]] == ["El libro de Alice"]
    assert export["shelf"][0]["review"] == "mi reseña"

    # ── Deletion: re-auth required, then complete erasure ─────
    wrong = await alice.request("DELETE", "/api/account", json={"password": "not-my-password"})
    assert wrong.status_code == 403

    gone = await alice.request("DELETE", "/api/account", json={"password": "long-enough-pass"})
    assert gone.status_code == 204

    assert (await alice.get("/api/auth/me")).status_code == 401  # session revoked

    async with factory() as check:
        users_left = (
            (await check.execute(text("SELECT email FROM users ORDER BY email"))).scalars().all()
        )
        shelf_left = (await check.execute(text("SELECT title FROM shelf_entries"))).scalars().all()
    assert users_left == ["bob@example.com"]  # Alice gone, Bob untouched
    assert shelf_left == ["El libro de Bob"]  # cascade took Alice's shelf

    # Bob's world keeps working.
    assert (await bob.get("/api/shelf")).status_code == 200
    await alice.aclose()
    await bob.aclose()
    await engine.dispose()
