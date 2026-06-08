"""ImportShelf — turn parsed Goodreads rows into matched, persisted shelf entries.

For each row we resolve a catalogue match with a clear precedence: an exact
ISBN-13 hit is authoritative; otherwise a conservative title(+author) trigram
match; otherwise the entry is kept unmatched (it can re-match for free as the
catalogue grows). Every row is upserted by (source, source_book_id) so a
re-import of an updated export is idempotent. Pure application logic — the
catalogue lookups and persistence are behind the `ShelfRepository` port.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bibliohack.reading_history.application.ports import ShelfEntryData
from bibliohack.reading_history.domain.shelf import MatchVia

if TYPE_CHECKING:
    from collections.abc import Iterable

    from bibliohack.reading_history.application.ports import ShelfRepository
    from bibliohack.reading_history.infrastructure.goodreads.csv_parser import GoodreadsRow


@dataclass(frozen=True, slots=True)
class ImportStats:
    """Outcome of an import run."""

    total: int = 0
    inserted: int = 0
    updated: int = 0
    matched_isbn: int = 0
    matched_title_author: int = 0
    unmatched: int = 0

    @property
    def matched(self) -> int:
        return self.matched_isbn + self.matched_title_author


class ImportShelf:
    """Match + persist a batch of Goodreads rows."""

    def __init__(self, *, repository: ShelfRepository, source: str = "goodreads") -> None:
        self._repo = repository
        self._source = source

    async def execute(self, rows: Iterable[GoodreadsRow]) -> ImportStats:
        total = inserted = updated = 0
        matched_isbn = matched_title = unmatched = 0

        for row in rows:
            total += 1
            record_id, via = await self._match(row)
            if via is MatchVia.ISBN:
                matched_isbn += 1
            elif via is MatchVia.TITLE_AUTHOR:
                matched_title += 1
            else:
                unmatched += 1

            was_new = await self._repo.upsert_entry(
                ShelfEntryData(
                    source=self._source,
                    source_book_id=row.source_book_id,
                    title=row.title,
                    author=row.author,
                    isbn_13=row.isbn_13,
                    shelf=row.shelf,
                    rating=row.rating,
                    review=row.review,
                    date_read=row.date_read,
                    date_added=row.date_added,
                    matched_record_id=record_id,
                    matched_via=via,
                )
            )
            if was_new:
                inserted += 1
            else:
                updated += 1

        return ImportStats(
            total=total,
            inserted=inserted,
            updated=updated,
            matched_isbn=matched_isbn,
            matched_title_author=matched_title,
            unmatched=unmatched,
        )

    async def _match(self, row: GoodreadsRow) -> tuple[str | None, MatchVia]:
        if row.isbn_13:
            record_id = await self._repo.match_isbn13(row.isbn_13)
            if record_id is not None:
                return record_id, MatchVia.ISBN
        record_id = await self._repo.match_title_author(row.title, row.author)
        if record_id is not None:
            return record_id, MatchVia.TITLE_AUTHOR
        return None, MatchVia.NONE
