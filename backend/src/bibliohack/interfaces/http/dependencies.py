"""Shared FastAPI dependencies — DB session, settings, …

The session dependency yields a per-request `AsyncSession` bound to the
process-wide async engine. We don't open a transaction here — read
endpoints don't need one, and write endpoints (none yet) can open their
own via `async with session.begin()`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

from bibliohack.shared.infrastructure.db import (
    make_engine,
    make_session_factory,
)
from bibliohack.shared.infrastructure.settings import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
    )


# Pydantic-settings `BaseSettings` instances aren't hashable, so we can't
# use them as lru_cache keys directly. Cache on the database_url string
# (which IS hashable). Tests swap the URL via env vars and a settings
# cache_clear, so this re-resolves on the next call.
@lru_cache(maxsize=1)
def _engine_factory_pair_for_url(
    _database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    settings = get_settings()
    engine = make_engine(settings)
    return engine, make_session_factory(engine)


def _engine_factory_pair(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    return _engine_factory_pair_for_url(settings.database_url)


# Re-export the inner cache_clear so tests (and any operator hot-reload
# code) can reset the engine without reaching into the private name.
_engine_factory_pair.cache_clear = _engine_factory_pair_for_url.cache_clear  # type: ignore[attr-defined]


async def get_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an open AsyncSession per request."""
    _, factory = _engine_factory_pair(settings)
    async with factory() as session:
        yield session
