"""DiscoverViaExpertQuery — seed `scrape_tasks` from an AbsysNET expert query.

The "novedades" discovery path (ARCHITECTURE.md §6.2, "expert-query slicing"):
run a publication-year query against the OPAC, collect the result TITNs, and
seed them as `discovered` tasks for the worker to ingest. Complements the
exhaustive TITN-range seeding (`SeedDiscoveredTasks`) — this is how we fill
the catalogue with *recent* records (which skew literary) rather than walking
the low-TITN institutional backlog.

Discovery is **resumable**: a persisted `DiscoveryCursor` records how far we've
paginated through the query's results list, so successive runs march through
the entire set (~55k for `@fepu>=2024`) instead of re-scanning page 1. Because
results are ordered by TITN ascending and new acquisitions get high TITNs (so
they append at the end), a forward cursor also naturally picks up new arrivals.

The OPAC-specific search + pagination lives in the gateway adapter
(`discover_slice`); this use case orchestrates cursor → discover → seed → save.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bibliohack.catalog.domain.titn import Titn

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import (
        DiscoveryCursorRepository,
        OpacSearchGateway,
        ScrapeTaskRepository,
    )


@dataclass(frozen=True, slots=True)
class DiscoverResult:
    """Outcome of one discovery run."""

    expression: str
    titns_found: int
    seeded: int  # newly-inserted scrape_tasks (already-known TITNs don't count)
    start_offset: int  # DOC offset this run resumed from
    next_offset: int  # DOC offset the next run will resume from
    total: int | None  # OPAC's reported result count for the query


def novedades_expression(*, year_from: int, year_to: int | None = None) -> str:
    """Build the AbsysNET expert query for records published in a year range.

    ``@fepu`` is the publication-date field. ``y`` is the AbsysNET AND
    operator. With only ``year_from`` we get "published since"; adding
    ``year_to`` bounds it on both ends.
    """
    if year_to is None:
        return f"(@fepu>={year_from})"
    return f"(@fepu>={year_from}) y (@fepu<={year_to})"


def isbn_expert_expression(isbn: str) -> str:
    """Build the AbsysNET expert query matching a record by ISBN (canon C3).

    The ``.tNNN.`` form targets a MARC tag; ISBN lives in MARC tag **020**, so
    ``(<isbn>.t020.)`` looks the ISBN up in that index (compare ``.t650.`` =
    subject, ``.titn.`` = record id). Confirmed against the live RBPA OPAC:
    ``(8425536001871.t020.)`` returns exactly the one holding that carries it.

    Used by the C3 "resolve" step to ask the OPAC whether the RBPA holds a
    canon-seed work by its ISBN-13 before falling back to title+author.
    """
    return f"({isbn.strip()}.t020.)"


class DiscoverViaExpertQuery:
    """Use case: resumably discover TITNs via an expert query and seed them."""

    def __init__(
        self,
        *,
        gateway: OpacSearchGateway,
        tasks: ScrapeTaskRepository,
        cursors: DiscoveryCursorRepository,
    ) -> None:
        self._gateway = gateway
        self._tasks = tasks
        self._cursors = cursors

    async def execute(
        self, expression: str, *, max_results: int, reset: bool = False
    ) -> DiscoverResult:
        cursor = None if reset else await self._cursors.get(expression)
        start_offset = cursor.next_offset if cursor else 0

        slice_ = await self._gateway.discover_slice(
            expression, start_offset=start_offset, max_results=max_results
        )

        seeded = 0
        for value in slice_.titns:
            if await self._tasks.seed_one(Titn(value)):
                seeded += 1

        # Advance the cursor; clamp at total so we don't run past the end.
        # When caught up, the cursor sits at `total` and each run picks up
        # whatever new records pushed `total` higher (they append at the end).
        next_offset = slice_.next_offset
        if slice_.total is not None and next_offset > slice_.total:
            next_offset = slice_.total
        await self._cursors.save(expression, next_offset=next_offset, total=slice_.total)

        return DiscoverResult(
            expression=expression,
            titns_found=len(slice_.titns),
            seeded=seeded,
            start_offset=start_offset,
            next_offset=next_offset,
            total=slice_.total,
        )
