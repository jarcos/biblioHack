"""MatchCanonSeed — link seed works to records the mirror already holds (C1).

DB-only, zero OPAC load. For each not-yet-matched seed row it resolves a
catalogue match with the same precedence as the Goodreads importer: an ISBN-13
hit is authoritative; otherwise a conservative title(+author) trigram match;
otherwise the row stays unmatched (it re-matches for free as the catalogue grows
via the novedades crawl or, later, C3 acquisition). The link feeds the C2
positive-only relevance boost and the coverage report that tells us how many
classics we hold today.

Pure application logic — lookups and the link write live behind the
``CanonSeedRepository`` port. Batched + bounded so it can run as a cheap nightly
sweep without holding one giant transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bibliohack.catalog.domain.canon import CanonMatchVia

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import (
        CanonSeedRepository,
        CanonSeedRow,
    )

DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class MatchStats:
    """Outcome of a match run (this invocation only — not the whole seed)."""

    scanned: int = 0
    matched_isbn: int = 0
    matched_title_author: int = 0
    unmatched: int = 0

    @property
    def matched(self) -> int:
        return self.matched_isbn + self.matched_title_author


class MatchCanonSeed:
    """Sweep unmatched seed rows and link the ones the mirror already holds."""

    def __init__(
        self,
        *,
        repository: CanonSeedRepository,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._repo = repository
        self._batch_size = max(1, batch_size)

    async def execute(self, *, max_rows: int | None = None) -> MatchStats:
        """Process up to `max_rows` unmatched rows (or all of them).

        Reads bounded batches of unmatched rows. A successful match flips a row
        out of ``iter_unmatched`` (its pool shrinks); rows we *couldn't* match
        stay in the pool, so we page past them with an ``offset`` that advances
        by the number left unmatched this batch — otherwise the same un-matchable
        rows would be re-read forever. The loop ends when a short/empty batch
        signals the pool is exhausted.
        """
        scanned = matched_isbn = matched_title = unmatched = 0
        offset = 0

        while max_rows is None or scanned < max_rows:
            remaining = None if max_rows is None else max_rows - scanned
            limit = self._batch_size if remaining is None else min(self._batch_size, remaining)
            rows = await self._repo.iter_unmatched(limit=limit, offset=offset)
            if not rows:
                break

            batch_unmatched = 0
            for row in rows:
                scanned += 1
                record_id, via = await self._match(row)
                if via is CanonMatchVia.ISBN:
                    matched_isbn += 1
                elif via is CanonMatchVia.TITLE_AUTHOR:
                    matched_title += 1
                else:
                    unmatched += 1
                    batch_unmatched += 1
                    continue
                assert record_id is not None
                await self._repo.link_match(row.id, record_id, via)

            # Matched rows leave the pool on their own; skip past the ones that
            # stayed unmatched so the next query returns fresh rows.
            offset += batch_unmatched
            if len(rows) < limit:
                break  # last (partial) page — pool exhausted

        return MatchStats(
            scanned=scanned,
            matched_isbn=matched_isbn,
            matched_title_author=matched_title,
            unmatched=unmatched,
        )

    async def _match(self, row: CanonSeedRow) -> tuple[str | None, CanonMatchVia]:
        if row.isbn13:
            record_id = await self._repo.match_isbn13(row.isbn13)
            if record_id is not None:
                return record_id, CanonMatchVia.ISBN
        record_id = await self._repo.match_title_author(row.title, row.author)
        if record_id is not None:
            return record_id, CanonMatchVia.TITLE_AUTHOR
        return None, CanonMatchVia.NONE
