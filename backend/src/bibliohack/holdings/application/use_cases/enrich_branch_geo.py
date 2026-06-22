"""EnrichBranchGeo — fill branch lat/lng from a geocoder (Libraries L0).

Off-OPAC. For each branch that has a municipality but no coordinates yet, geocode
the town centroid and store it. The result lets the browser distance-sort the
branch list for the proximity picker (L2); coordinates never depend on, or touch,
the user's location.

Polite + terminating: successfully geocoded branches drop out of the ungeocoded
pool; branches that miss/err are left NULL to retry on a future run, and the
sweep pages past them with an ``offset`` so a transient miss can't re-read the
same branch forever. ``pause_seconds`` paces calls to honour Nominatim's
1 req/s policy. Bounded per run via ``max_branches``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bibliohack.holdings.application.ports import BranchGeoRepository, Geocoder

DEFAULT_BATCH_SIZE = 50
DEFAULT_PAUSE_SECONDS = 1.1  # Nominatim policy: ≤ 1 req/s.


@dataclass(frozen=True, slots=True)
class GeocodeStats:
    """Outcome of one enrich run (this invocation only)."""

    scanned: int = 0
    geocoded: int = 0  # resolved to coordinates
    missed: int = 0  # no result / error (left for retry)


class EnrichBranchGeo:
    """Geocode branches lacking coordinates, politely and resumably."""

    def __init__(
        self,
        *,
        geocoder: Geocoder,
        repository: BranchGeoRepository,
        batch_size: int = DEFAULT_BATCH_SIZE,
        pause_seconds: float = DEFAULT_PAUSE_SECONDS,
        commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._geocoder = geocoder
        self._repo = repository
        self._batch_size = max(1, batch_size)
        self._pause = max(0.0, pause_seconds)
        # Commit hook so a long run persists progress per batch and survives an
        # interruption (a 500-branch geocode is ~10 min — too long for one tx).
        self._commit = commit

    async def execute(self, *, max_branches: int | None = None) -> GeocodeStats:
        scanned = geocoded = missed = 0
        offset = 0

        while max_branches is None or scanned < max_branches:
            remaining = None if max_branches is None else max_branches - scanned
            limit = self._batch_size if remaining is None else min(self._batch_size, remaining)
            rows = await self._repo.iter_ungeocoded(limit=limit, offset=offset)
            if not rows:
                break

            batch_missed = 0
            for row in rows:
                scanned += 1
                if not row.municipality:
                    missed += 1
                    batch_missed += 1
                    continue
                coords = await self._geocoder.geocode(
                    municipality=row.municipality, province=row.province
                )
                if coords is None:
                    missed += 1
                    batch_missed += 1
                else:
                    await self._repo.set_geo(row.code, lat=coords[0], lng=coords[1])
                    geocoded += 1
                if self._pause:
                    await asyncio.sleep(self._pause)

            # Persist this batch's writes before moving on, so an interruption
            # keeps progress (and a re-run resumes from the remaining NULLs).
            if self._commit is not None:
                await self._commit()

            # Geocoded branches leave the queue; page past the ones still NULL.
            offset += batch_missed
            if len(rows) < limit:
                break

        return GeocodeStats(scanned=scanned, geocoded=geocoded, missed=missed)
