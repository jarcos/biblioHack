"""Postgres-backed `AvailabilitySnapshotRepository`.

Bulk-inserts new snapshots into the TimescaleDB hypertable using
ON CONFLICT DO NOTHING on the (copy_id, observed_at) primary key — so
re-running the same scrape within the same second is idempotent.

Operates inside the caller's session/transaction. Doesn't commit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert

from bibliohack.availability.infrastructure.postgres.models import (
    AvailabilitySnapshotModel,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

    from bibliohack.availability.domain.snapshot import AvailabilitySnapshot


class PostgresAvailabilitySnapshotRepository:
    """Concrete `AvailabilitySnapshotRepository` backed by SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, snapshots: Iterable[AvailabilitySnapshot]) -> int:
        """Append the given snapshots, return the count actually inserted.

        Skips rows whose (copy_id, observed_at) already exists.
        """
        rows = [
            {
                "copy_id": s.copy_id,
                "observed_at": s.observed_at,
                "status": s.status.value,
                "raw_status": None,
                "due_back_at": s.due_back_at,
            }
            for s in snapshots
        ]
        if not rows:
            return 0

        # `RETURNING` on ON CONFLICT DO NOTHING gives us back only the rows
        # that were actually inserted — that's our count.
        stmt = (
            pg_insert(AvailabilitySnapshotModel)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["copy_id", "observed_at"],
            )
            .returning(AvailabilitySnapshotModel.copy_id)
        )
        result = await self._session.execute(stmt)
        return len(result.fetchall())
