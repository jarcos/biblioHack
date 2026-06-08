"""Postgres-backed `ShelfRepository`: catalogue matching + shelf upserts.

Matching uses the `isbns` table for the authoritative path and pg_trgm
`similarity()` (already enabled for the contributor name index) for the title/
author fallback, with conservative thresholds so only confident links are made.
Upserts are `ON CONFLICT (source, source_book_id) DO UPDATE` and report
insert-vs-update via the `xmax = 0` trick.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bibliohack.catalog.infrastructure.postgres.models import (
    BibliographicRecordModel,
    ContributorModel,
    IsbnModel,
)
from bibliohack.reading_history.infrastructure.postgres.models import ShelfEntryModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from bibliohack.reading_history.application.ports import ShelfEntryData

# Trigram thresholds. Precision over recall: a wrong match pollutes the shelf,
# whereas a miss simply stays re-checkable as the catalogue grows. Author names
# differ in ordering across sources ("Salman Rushdie" vs "Rushdie, Salman") but
# trigrams are substring-based, so a modest author floor still helps.
_TITLE_SIMILARITY_MIN = 0.5
_AUTHOR_SIMILARITY_MIN = 0.3


class PostgresShelfRepository:
    """Concrete `ShelfRepository` backed by SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def match_isbn13(self, isbn13: str) -> str | None:
        record_id = (
            await self._session.execute(
                select(IsbnModel.record_id).where(IsbnModel.isbn == isbn13).limit(1)
            )
        ).scalar_one_or_none()
        return str(record_id) if record_id is not None else None

    async def match_title_author(self, title: str, author: str | None) -> str | None:
        title_sim = func.similarity(BibliographicRecordModel.title, title)
        stmt = (
            select(BibliographicRecordModel.id)
            .where(title_sim >= _TITLE_SIMILARITY_MIN)
            .order_by(title_sim.desc())
            .limit(1)
        )
        if author:
            author_match = (
                select(ContributorModel.record_id)
                .where(
                    ContributorModel.record_id == BibliographicRecordModel.id,
                    ContributorModel.role == "author",
                    func.similarity(ContributorModel.name, author) >= _AUTHOR_SIMILARITY_MIN,
                )
                .exists()
            )
            stmt = stmt.where(author_match)

        record_id = (await self._session.execute(stmt)).scalar_one_or_none()
        return str(record_id) if record_id is not None else None

    async def upsert_entry(self, entry: ShelfEntryData) -> bool:
        values = {
            "id": uuid4(),
            "source": entry.source,
            "source_book_id": entry.source_book_id,
            "title": entry.title,
            "author": entry.author,
            "isbn_13": entry.isbn_13,
            "shelf": entry.shelf.value,
            "rating": entry.rating,
            "review": entry.review,
            "date_read": entry.date_read,
            "date_added": entry.date_added,
            "matched_record_id": (
                UUID(entry.matched_record_id) if entry.matched_record_id is not None else None
            ),
            "matched_via": entry.matched_via.value,
        }
        insert_stmt = pg_insert(ShelfEntryModel).values(**values)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            constraint="uq_shelf_entries_source_book",
            set_={
                "title": insert_stmt.excluded.title,
                "author": insert_stmt.excluded.author,
                "isbn_13": insert_stmt.excluded.isbn_13,
                "shelf": insert_stmt.excluded.shelf,
                "rating": insert_stmt.excluded.rating,
                "review": insert_stmt.excluded.review,
                "date_read": insert_stmt.excluded.date_read,
                "date_added": insert_stmt.excluded.date_added,
                "matched_record_id": insert_stmt.excluded.matched_record_id,
                "matched_via": insert_stmt.excluded.matched_via,
                "updated_at": func.now(),
            },
        )
        # `xmax = 0` is true only for a freshly inserted tuple; on the UPDATE
        # branch of ON CONFLICT the conflicting tuple's xmax is non-zero.
        inserted: bool = (
            await self._session.execute(upsert_stmt.returning(literal_column("(xmax = 0)")))
        ).scalar_one()
        return bool(inserted)
