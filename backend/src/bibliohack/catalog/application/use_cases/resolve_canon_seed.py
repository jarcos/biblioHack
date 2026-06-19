"""ResolveCanonSeed — ask the OPAC whether the RBPA holds an unmatched classic (C3).

The demand-driven acquisition step (see ``docs/design/canon-import.md`` →
"Pipeline" / "Ops"). For each canon-seed work the C1 matcher *couldn't* find in
the mirror, query the live OPAC by ISBN — the precise, confirmed key
(``isbn_expert_expression`` → MARC tag 020). If the RBPA holds it, seed the
returned TITN(s) into ``scrape_tasks`` so the **existing** scrape worker ingests
the record with real copies + availability, and mark the seed ``held``; if the
OPAC returns nothing for any of the work's ISBNs, mark it ``not_held`` — we
never invent a phantom record for something the libraries don't hold.

This is the one canon step that touches the OPAC, so it is **polite by
construction**: it runs through the shared throttle (1 req/s) on the crawl
plane, is bounded per run (``max_rows``), and stops querying a work's ISBNs as
soon as one resolves (break-on-first-hit) to spend the request budget frugally.
Title+author resolve is intentionally deferred (free-text OPAC results need
careful precision handling); ISBN-less seeds are simply left ``unchecked``.

Pure application logic — the OPAC search and persistence sit behind the
``OpacSearchGateway`` / ``CanonSeedRepository`` / ``ScrapeTaskRepository`` ports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bibliohack.catalog.application.use_cases.discover_via_search import (
    isbn_expert_expression,
)
from bibliohack.catalog.domain.canon import AcquireStatus
from bibliohack.catalog.domain.titn import Titn

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bibliohack.catalog.application.ports import (
        CanonSeedRepository,
        CanonSeedRow,
        OpacSearchGateway,
        ScrapeTaskRepository,
    )

DEFAULT_BATCH_SIZE = 100
# Per ISBN query: a held work resolves to one (or a few) editions; we only need
# enough TITNs to seed the work into the mirror, not the whole results list.
DEFAULT_MAX_RESULTS_PER_QUERY = 5


@dataclass(frozen=True, slots=True)
class ResolveStats:
    """Outcome of a resolve run (this invocation only)."""

    scanned: int = 0
    held: int = 0
    not_held: int = 0
    titns_seeded: int = 0

    @property
    def checked(self) -> int:
        return self.held + self.not_held


class ResolveCanonSeed:
    """Resolve unmatched seed works against the live OPAC by ISBN."""

    def __init__(
        self,
        *,
        gateway: OpacSearchGateway,
        repository: CanonSeedRepository,
        tasks: ScrapeTaskRepository,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_results_per_query: int = DEFAULT_MAX_RESULTS_PER_QUERY,
    ) -> None:
        self._gateway = gateway
        self._repo = repository
        self._tasks = tasks
        self._batch_size = max(1, batch_size)
        self._max_results = max(1, max_results_per_query)

    async def execute(self, *, max_rows: int | None = None) -> ResolveStats:
        """Resolve up to `max_rows` eligible seed works (or all of them).

        Resolving a work changes its ``acquire_status`` (``held``/``not_held``),
        so it drops out of ``iter_resolvable`` — each batch is fresh and the loop
        ends when a batch comes back empty.
        """
        scanned = held = not_held = titns_seeded = 0

        while max_rows is None or scanned < max_rows:
            remaining = None if max_rows is None else max_rows - scanned
            limit = self._batch_size if remaining is None else min(self._batch_size, remaining)
            rows = await self._repo.iter_resolvable(limit=limit)
            if not rows:
                break

            for row in rows:
                scanned += 1
                titns = await self._resolve_by_isbn(row)
                if titns:
                    for value in titns:
                        if await self._tasks.seed_one(Titn(value)):
                            titns_seeded += 1
                    await self._repo.set_acquire_status(row.id, AcquireStatus.HELD)
                    held += 1
                else:
                    await self._repo.set_acquire_status(row.id, AcquireStatus.NOT_HELD)
                    not_held += 1

        return ResolveStats(
            scanned=scanned,
            held=held,
            not_held=not_held,
            titns_seeded=titns_seeded,
        )

    async def _resolve_by_isbn(self, row: CanonSeedRow) -> list[int]:
        """Return the OPAC TITNs holding any of the work's ISBNs.

        Stops at the first ISBN that resolves (break-on-first-hit) — finding one
        held edition is enough to pull the work into the mirror, and it spares
        the OPAC the remaining lookups.
        """
        for isbn in row.isbn13:
            slice_ = await self._gateway.discover_slice(
                isbn_expert_expression(isbn),
                start_offset=0,
                max_results=self._max_results,
            )
            if slice_.titns:
                return _unique(slice_.titns)
        return []


def _unique(values: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
