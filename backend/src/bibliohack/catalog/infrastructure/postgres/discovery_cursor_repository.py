"""Postgres-backed `DiscoveryCursorRepository`.

Stores one row per expert-query expression recording how far discovery has
paginated through its results list, so `bibliohack catalog discover` resumes
where it left off instead of re-scanning page 1 every run.

Takes an `AsyncSession` so it participates in the caller's transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bibliohack.catalog.application.ports import DiscoveryCursor
from bibliohack.catalog.infrastructure.postgres.models import DiscoveryCursorModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PostgresDiscoveryCursorRepository:
    """Concrete `DiscoveryCursorRepository` backed by `discovery_cursors`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, expression: str) -> DiscoveryCursor | None:
        row = await self._session.get(DiscoveryCursorModel, expression)
        if row is None:
            return None
        return DiscoveryCursor(
            expression=row.expression, next_offset=row.next_offset, total=row.total
        )

    async def save(self, expression: str, *, next_offset: int, total: int | None) -> None:
        stmt = (
            pg_insert(DiscoveryCursorModel)
            .values(expression=expression, next_offset=next_offset, total=total)
            .on_conflict_do_update(
                index_elements=["expression"],
                set_={"next_offset": next_offset, "total": total, "updated_at": func.now()},
            )
        )
        await self._session.execute(stmt)

    async def list_all(self) -> list[DiscoveryCursor]:
        """All cursors — handy for a future progress dashboard."""
        rows = (await self._session.execute(select(DiscoveryCursorModel))).scalars().all()
        return [
            DiscoveryCursor(expression=r.expression, next_offset=r.next_offset, total=r.total)
            for r in rows
        ]
