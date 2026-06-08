"""Postgres-backed read side for the bookshelf (`GET /shelf`).

Loads shelf entries and, for the ones matched to a catalogue record, enriches
them with the same `CatalogRecordSummary` projection search uses (cover +
availability + copies), via the catalog read repository's
`summaries_by_record_ids`. Ordering puts most-recently-read first, then
recently-added, so the UI's shelves read naturally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from bibliohack.catalog.infrastructure.postgres.catalog_read_repository import (
    PostgresCatalogReadRepository,
)
from bibliohack.reading_history.application.dto import ShelfEntryView
from bibliohack.reading_history.infrastructure.postgres.models import ShelfEntryModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PostgresShelfReadRepository:
    """Read-only projection of the shelf for the public API."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_entries(self) -> list[ShelfEntryView]:
        stmt = select(ShelfEntryModel).order_by(
            ShelfEntryModel.date_read.desc().nullslast(),
            ShelfEntryModel.date_added.desc().nullslast(),
            ShelfEntryModel.title.asc(),
        )
        rows = list((await self._session.execute(stmt)).scalars().all())

        matched_ids = [r.matched_record_id for r in rows if r.matched_record_id is not None]
        summaries = await PostgresCatalogReadRepository(self._session).summaries_by_record_ids(
            matched_ids
        )

        return [
            ShelfEntryView(
                source_book_id=r.source_book_id,
                title=r.title,
                author=r.author,
                isbn_13=r.isbn_13,
                shelf=r.shelf,
                rating=r.rating,
                date_read=r.date_read.isoformat() if r.date_read is not None else None,
                matched_via=r.matched_via,
                match=(
                    summaries.get(r.matched_record_id) if r.matched_record_id is not None else None
                ),
            )
            for r in rows
        ]
