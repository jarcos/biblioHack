"""RematchShelf — link still-unmatched shelf entries to records the mirror now holds.

The companion to the demand-driven fetcher (kanban "Demand-driven fetcher
(unmatched shelf books)"). Matching only happens at import time inside
``ImportShelf``; an entry that was unmatched then stays unmatched even after the
novedades crawl (or the fetcher's own OPAC resolve → worker ingest) brings its
record into the catalogue. This use case closes that gap: it walks unmatched
entries and re-runs the **same** conservative match — ISBN-13 first, then a
title+author trigram fallback — linking the ones the mirror can now resolve.

DB-only and idempotent: it touches the OPAC zero times (it only reads the
catalogue we already hold), so it ships value on the app/CD plane with no crawl
budget. Bounded by ``limit`` so a periodic run is cheap. Pure application logic
behind the ``ShelfRepository`` port; the resolve-by-OPAC half is a separate use
case (the on-OPAC step) that seeds records for the worker — this one only links
what's already ingested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bibliohack.reading_history.domain.shelf import MatchVia

if TYPE_CHECKING:
    from bibliohack.reading_history.application.ports import (
        ShelfRepository,
        UnmatchedShelfEntry,
    )

DEFAULT_BATCH_SIZE = 200


@dataclass(frozen=True, slots=True)
class RematchStats:
    """Outcome of a re-match run (this invocation only)."""

    scanned: int = 0
    linked_isbn: int = 0
    linked_title_author: int = 0

    @property
    def linked(self) -> int:
        return self.linked_isbn + self.linked_title_author


class RematchShelf:
    """Re-link unmatched shelf entries against the current catalogue."""

    def __init__(
        self, *, repository: ShelfRepository, batch_size: int = DEFAULT_BATCH_SIZE
    ) -> None:
        self._repo = repository
        self._batch_size = max(1, batch_size)

    async def execute(self, *, max_rows: int | None = None) -> RematchStats:
        """Re-match up to `max_rows` unmatched entries (or all of them).

        Linking an entry sets its `matched_record_id`, so it drops out of
        `iter_unmatched` — each batch is fresh and the loop ends when a batch
        comes back empty (or the cap is hit). A batch that links nothing also
        terminates the loop: its rows are unchanged, so the next identical query
        would spin forever otherwise.
        """
        scanned = linked_isbn = linked_title = 0

        while max_rows is None or scanned < max_rows:
            remaining = None if max_rows is None else max_rows - scanned
            limit = self._batch_size if remaining is None else min(self._batch_size, remaining)
            rows = await self._repo.iter_unmatched(limit=limit)
            if not rows:
                break

            linked_this_batch = 0
            for row in rows:
                scanned += 1
                via = await self._match(row)
                if via is MatchVia.ISBN:
                    linked_isbn += 1
                    linked_this_batch += 1
                elif via is MatchVia.TITLE_AUTHOR:
                    linked_title += 1
                    linked_this_batch += 1

            # No links → the same unmatched rows would come back next iteration.
            # Stop rather than loop forever on a stable, unresolvable head.
            if linked_this_batch == 0:
                break

        return RematchStats(
            scanned=scanned,
            linked_isbn=linked_isbn,
            linked_title_author=linked_title,
        )

    async def _match(self, entry: UnmatchedShelfEntry) -> MatchVia:
        """ISBN-13 first (authoritative), then a conservative title+author match."""
        if entry.isbn_13:
            record_id = await self._repo.match_isbn13(entry.isbn_13)
            if record_id is not None:
                await self._repo.link_match(entry.id, record_id, MatchVia.ISBN)
                return MatchVia.ISBN

        record_id = await self._repo.match_title_author(entry.title, entry.author)
        if record_id is not None:
            await self._repo.link_match(entry.id, record_id, MatchVia.TITLE_AUTHOR)
            return MatchVia.TITLE_AUTHOR

        return MatchVia.NONE
