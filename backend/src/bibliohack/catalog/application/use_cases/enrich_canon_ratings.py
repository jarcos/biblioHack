"""EnrichCanonRatings — populate canon_seed.ol_rating_count from Open Library (C4).

Off-OPAC popularity enrichment. For each seed row that has an ISBN but no Open
Library ratings count yet, look the count up (by the first ISBN) and store it.
The stored signal deepens canon notability; wiring it into the relevance blend
is a separate, isolated change (this only collects the data).

Polite + terminating: rows whose lookup succeeds get a value and drop out of the
unrated pool; rows whose lookup *fails* (transport / non-200 → ``None``) are left
NULL to retry on a future run, and the sweep pages past them with an ``offset``
so a transient error can't re-read the same row forever. Bounded per run.

Pure application logic — the OL HTTP call and persistence sit behind the
``CanonRatingsSource`` / ``CanonSeedRepository`` ports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import (
        CanonRatingsSource,
        CanonSeedRepository,
    )

DEFAULT_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class EnrichStats:
    """Outcome of an enrich run (this invocation only)."""

    scanned: int = 0
    rated: int = 0  # lookups that returned a count (incl. 0)
    with_ratings: int = 0  # of those, how many had count > 0
    failed: int = 0  # lookups that couldn't be determined (left for retry)


class EnrichCanonRatings:
    """Fill ol_rating_count for ISBN-bearing seed rows from Open Library."""

    def __init__(
        self,
        *,
        source: CanonRatingsSource,
        repository: CanonSeedRepository,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._source = source
        self._repo = repository
        self._batch_size = max(1, batch_size)

    async def execute(self, *, max_rows: int | None = None) -> EnrichStats:
        scanned = rated = with_ratings = failed = 0
        offset = 0

        while max_rows is None or scanned < max_rows:
            remaining = None if max_rows is None else max_rows - scanned
            limit = self._batch_size if remaining is None else min(self._batch_size, remaining)
            rows = await self._repo.iter_unrated(limit=limit, offset=offset)
            if not rows:
                break

            batch_failed = 0
            for row in rows:
                scanned += 1
                count = await self._source.fetch_rating_count(row.isbn13[0])
                if count is None:
                    failed += 1
                    batch_failed += 1
                    continue
                await self._repo.set_rating_count(row.id, count)
                rated += 1
                if count > 0:
                    with_ratings += 1

            # Rated rows leave the unrated pool; page past the ones that failed
            # (still NULL) so the next query returns fresh rows.
            offset += batch_failed
            if len(rows) < limit:
                break

        return EnrichStats(
            scanned=scanned,
            rated=rated,
            with_ratings=with_ratings,
            failed=failed,
        )
