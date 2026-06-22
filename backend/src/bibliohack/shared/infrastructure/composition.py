"""Composition helpers — wire ports to concrete adapters for CLI / worker.

The FastAPI app gets its DI from `Depends`; the CLI and one-off workers
don't have that luxury, so this module provides a small async context
manager that yields a ready-to-use `AsyncSession` inside a transaction
that auto-commits on clean exit and rolls back on exception.

Keeps the CLI subcommand bodies focused on use-case orchestration rather
than session-management boilerplate.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from bibliohack.shared.infrastructure.db import (
    make_engine,
    make_session_factory,
)
from bibliohack.shared.infrastructure.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def transactional_session() -> AsyncIterator[AsyncSession]:
    """Open an engine + session bound to settings.database_url for one transaction.

    Yields an `AsyncSession`. On clean exit, commits. On exception, rolls back.
    Engine is disposed when the context exits either way.

    Use from CLI commands like::

        async def main() -> None:
            async with transactional_session() as session:
                repo = PostgresScrapeTaskRepository(session)
                ...
    """
    settings = get_settings()
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            yield session
    finally:
        await engine.dispose()


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession]:
    """Like :func:`transactional_session` but *without* a wrapping transaction.

    For long-running CLI jobs that need to **commit incrementally** (per batch)
    so progress survives an interruption, rather than one all-or-nothing
    transaction. The caller is responsible for calling ``session.commit()``.
    Engine is disposed on exit.
    """
    settings = get_settings()
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
