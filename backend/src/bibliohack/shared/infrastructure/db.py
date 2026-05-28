"""Async SQLAlchemy engine + session factory.

A single async engine is created once per process (lifespan-scoped) and
shared. Sessions are short-lived, request-scoped, and provided to use cases
via FastAPI's `Depends`.

This module is intentionally the only place that knows the connection URL —
everything else uses the `AsyncSession` it hands out.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.engine import Connection  # noqa: F401  (re-exported via type hints)

    from bibliohack.shared.infrastructure.settings import Settings


class Base(DeclarativeBase):
    """Single declarative base shared by all SQLAlchemy models across contexts.

    Having one Base means Alembic's autogenerate can see every table from a
    single `target_metadata = Base.metadata` reference. Models live in their
    bounded context's `infrastructure/postgres/models.py` but inherit from
    this same Base.
    """


def make_engine(settings: Settings) -> AsyncEngine:
    """Create an `AsyncEngine` from settings. Call once per process."""
    return create_async_engine(
        settings.database_url,
        echo=settings.app_env == "development" and False,  # set True to see SQL
        pool_pre_ping=True,
        future=True,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


@asynccontextmanager
async def transactional_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Convenience: open a session, begin a transaction, commit/rollback at exit."""
    async with factory() as session, session.begin():
        yield session
