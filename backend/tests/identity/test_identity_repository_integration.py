"""Integration tests for the identity Postgres adapters.

Real Postgres via testcontainers with migrations applied — exercises the
CITEXT case-insensitive email uniqueness, the user round-trip, and the
hashed/expiring/single-use token semantics of `PostgresTokenService`.
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from bibliohack.identity.application.ports import TokenPurpose
from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.infrastructure.postgres.token_service import PostgresTokenService
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository

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
            text("TRUNCATE users, email_verification_tokens, password_reset_tokens CASCADE")
        )
    async with factory() as s, s.begin():
        yield s
    await engine.dispose()


def _user(email: str = "jose@example.com") -> User:
    return User.register(
        email=Email(email),
        password_hash=PasswordHash("$argon2id$fake"),
        display_name="José",
    )


async def test_user_round_trip_and_flag_updates(session: AsyncSession) -> None:
    repo = PostgresUserRepository(session)
    user = _user()
    await repo.add(user)

    loaded = await repo.get_by_id(str(user.id))
    assert loaded is not None
    assert loaded.email.value == "jose@example.com"
    assert not loaded.email_verified

    await repo.set_email_verified(str(user.id))
    await repo.update_password_hash(str(user.id), "$argon2id$new")
    refreshed = await repo.get_by_id(str(user.id))
    assert refreshed is not None
    assert refreshed.email_verified
    assert refreshed.password_hash.value == "$argon2id$new"


async def test_email_lookup_is_case_insensitive_via_citext(session: AsyncSession) -> None:
    repo = PostgresUserRepository(session)
    await repo.add(_user())
    # The repository receives normalized (lowercase) emails from use cases,
    # but CITEXT means even a raw mixed-case probe hits.
    assert await repo.get_by_email("JOSE@EXAMPLE.COM") is not None
    assert await repo.get_by_email("ghost@example.com") is None


async def test_tokens_are_purpose_bound_and_single_use(session: AsyncSession) -> None:
    repo = PostgresUserRepository(session)
    tokens = PostgresTokenService(session)
    user = _user()
    await repo.add(user)

    raw = await tokens.issue(str(user.id), TokenPurpose.EMAIL_VERIFICATION)
    assert len(raw) >= 43  # 256 bits, url-safe

    # The raw token is never stored.
    stored = (
        await session.execute(text("SELECT token_hash FROM email_verification_tokens"))
    ).scalar_one()
    assert stored != raw

    # Wrong purpose misses; right purpose consumes exactly once.
    assert await tokens.consume(raw, TokenPurpose.PASSWORD_RESET) is None
    assert await tokens.consume(raw, TokenPurpose.EMAIL_VERIFICATION) == str(user.id)
    assert await tokens.consume(raw, TokenPurpose.EMAIL_VERIFICATION) is None


async def test_expired_tokens_do_not_redeem(session: AsyncSession) -> None:
    repo = PostgresUserRepository(session)
    tokens = PostgresTokenService(session)
    user = _user()
    await repo.add(user)

    raw = await tokens.issue(str(user.id), TokenPurpose.PASSWORD_RESET)
    await session.execute(
        text("UPDATE password_reset_tokens SET expires_at = :past"),
        {"past": datetime.now(UTC) - timedelta(seconds=1)},
    )
    assert await tokens.consume(raw, TokenPurpose.PASSWORD_RESET) is None
