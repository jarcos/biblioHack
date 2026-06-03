"""DiscoverViaExpertQuery — seed `scrape_tasks` from an AbsysNET expert query.

The "novedades" discovery path (ARCHITECTURE.md §6.2, "expert-query slicing"):
run a publication-year query against the OPAC, collect the result TITNs, and
seed them as `discovered` tasks for the worker to ingest. Complements the
exhaustive TITN-range seeding (`SeedDiscoveredTasks`) — this is how we fill
the catalogue with *recent* records (which skew literary) rather than walking
the low-TITN institutional backlog.

The OPAC-specific search + pagination lives in the gateway adapter
(`discover_titns`); this use case just orchestrates discover → seed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bibliohack.catalog.domain.titn import Titn

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import OpacSearchGateway, ScrapeTaskRepository


@dataclass(frozen=True, slots=True)
class DiscoverResult:
    """Outcome of one discovery run."""

    expression: str
    titns_found: int
    seeded: int  # newly-inserted scrape_tasks (already-known TITNs don't count)


def novedades_expression(*, year_from: int, year_to: int | None = None) -> str:
    """Build the AbsysNET expert query for records published in a year range.

    ``@fepu`` is the publication-date field. ``y`` is the AbsysNET AND
    operator. With only ``year_from`` we get "published since"; adding
    ``year_to`` bounds it on both ends.
    """
    if year_to is None:
        return f"(@fepu>={year_from})"
    return f"(@fepu>={year_from}) y (@fepu<={year_to})"


class DiscoverViaExpertQuery:
    """Use case: discover TITNs via an expert query and seed them for the worker."""

    def __init__(self, *, gateway: OpacSearchGateway, tasks: ScrapeTaskRepository) -> None:
        self._gateway = gateway
        self._tasks = tasks

    async def execute(self, expression: str, *, max_results: int) -> DiscoverResult:
        titns = await self._gateway.discover_titns(expression, max_results=max_results)
        seeded = 0
        for value in titns:
            if await self._tasks.seed_one(Titn(value)):
                seeded += 1
        return DiscoverResult(expression=expression, titns_found=len(titns), seeded=seeded)
