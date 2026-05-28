"""SeedDiscoveredTasks — populate `scrape_tasks` for a TITN range.

Pure orchestration. The CLI calls this once with a `(low, high)` pair that
typically comes from `ProbeTitnRange`'s output. Idempotent — re-running with
overlapping ranges only inserts the rows that aren't yet known, returning
the count of NEW rows.

Real-world example:

    >>> probe = await ProbeTitnRange(gateway).execute()
    >>> seeded = await SeedDiscoveredTasks(repo).execute(Titn(1), probe.highest_existing)
    >>> seeded.inserted
    1_234_567   # roughly the size of the Andalusian catalog

The worker then picks these up via `claim_next_batch`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import ScrapeTaskRepository
    from bibliohack.catalog.domain.titn import Titn


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Outcome of a single seed run."""

    range_low: int
    range_high: int
    inserted: int

    @property
    def range_size(self) -> int:
        return self.range_high - self.range_low + 1

    @property
    def already_known(self) -> int:
        return self.range_size - self.inserted


class SeedDiscoveredTasks:
    """Use case: fill `scrape_tasks` with `discovered` rows for [low, high]."""

    def __init__(self, repository: ScrapeTaskRepository) -> None:
        self._repository = repository

    async def execute(self, low: Titn, high: Titn) -> SeedResult:
        if int(low) > int(high):
            msg = f"low ({low}) must be <= high ({high})"
            raise ValueError(msg)
        inserted = await self._repository.seed_range(low, high)
        return SeedResult(
            range_low=int(low),
            range_high=int(high),
            inserted=inserted,
        )
