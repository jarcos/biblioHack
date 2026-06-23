"""ResolveUnmatchedShelf — the demand-driven fetcher's on-OPAC step.

The user-shelf sibling of canon C3 (``catalog/.../resolve_canon_seed.py``). For
each still-unmatched shelf *book* — deduped across users by the repository, so a
title on five shelves is one query — ask the live OPAC whether the RBPA holds it:
by ISBN first (MARC tag 020, the precise key), then a precise title+author expert
query as a fallback. If held, seed the returned TITN(s) into ``scrape_tasks`` so
the **existing** scrape worker ingests the record with real copies + availability,
and mark every entry in the group ``held``; if nothing comes back, mark them
``not_held`` — we never invent a phantom record for a book the libraries don't
hold. A later ``shelf rematch`` links the entries once the worker has ingested.

Polite by construction, exactly like the canon resolve: it runs through the shared
throttle on the crawl plane, is bounded per run (``max_rows`` distinct books),
stops querying a book's ISBNs as soon as one resolves (break-on-first-hit), and
seeds at most ``max_results_per_query`` TITNs per book. Pure application logic —
the OPAC search and persistence sit behind the ``OpacSearchGateway`` /
``ShelfRepository`` / ``ScrapeTaskRepository`` ports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bibliohack.catalog.application.use_cases.discover_via_search import (
    isbn_expert_expression,
    title_author_expert_expression,
)
from bibliohack.catalog.domain.titn import Titn
from bibliohack.reading_history.domain.shelf import ShelfResolveStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bibliohack.catalog.application.ports import OpacSearchGateway, ScrapeTaskRepository
    from bibliohack.reading_history.application.ports import (
        ResolvableShelfBook,
        ShelfRepository,
    )

DEFAULT_BATCH_SIZE = 100
# Per ISBN query: a held book resolves to one (or a few) editions; we only need
# enough TITNs to seed the book into the mirror, not the whole results list.
DEFAULT_MAX_RESULTS_PER_QUERY = 5
# Re-try a `not_held` book this many days after the last attempt — the mirror
# keeps growing, so a book the RBPA "doesn't hold" today may be held later.
DEFAULT_COOLDOWN_DAYS = 30


@dataclass(frozen=True, slots=True)
class ShelfResolveStats:
    """Outcome of a resolve run (this invocation only)."""

    scanned: int = 0
    held: int = 0
    not_held: int = 0
    entries_marked: int = 0
    titns_seeded: int = 0

    @property
    def checked(self) -> int:
        return self.held + self.not_held


class ResolveUnmatchedShelf:
    """Resolve unmatched shelf books against the live OPAC, seeding held TITNs."""

    def __init__(
        self,
        *,
        gateway: OpacSearchGateway,
        repository: ShelfRepository,
        tasks: ScrapeTaskRepository,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_results_per_query: int = DEFAULT_MAX_RESULTS_PER_QUERY,
        cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    ) -> None:
        self._gateway = gateway
        self._repo = repository
        self._tasks = tasks
        self._batch_size = max(1, batch_size)
        self._max_results = max(1, max_results_per_query)
        self._cooldown_days = max(0, cooldown_days)

    async def execute(self, *, max_rows: int | None = None) -> ShelfResolveStats:
        """Resolve up to `max_rows` eligible books (or all currently eligible).

        Resolving a book stamps its entries' `resolve_status` (+ `last_resolved_at`),
        so a `held` book leaves `iter_resolvable_books` for good and a `not_held`
        one leaves until the cooldown lapses — each batch is fresh and the loop
        ends when a batch comes back empty.
        """
        scanned = held = not_held = entries_marked = titns_seeded = 0

        while max_rows is None or scanned < max_rows:
            remaining = None if max_rows is None else max_rows - scanned
            limit = self._batch_size if remaining is None else min(self._batch_size, remaining)
            books = await self._repo.iter_resolvable_books(
                limit=limit, cooldown_days=self._cooldown_days
            )
            if not books:
                break

            for book in books:
                scanned += 1
                titns = await self._resolve(book)
                if titns:
                    for value in titns:
                        if await self._tasks.seed_one(Titn(value)):
                            titns_seeded += 1
                    await self._repo.mark_resolve_result(book.entry_ids, ShelfResolveStatus.HELD)
                    held += 1
                else:
                    await self._repo.mark_resolve_result(
                        book.entry_ids, ShelfResolveStatus.NOT_HELD
                    )
                    not_held += 1
                entries_marked += len(book.entry_ids)

        return ShelfResolveStats(
            scanned=scanned,
            held=held,
            not_held=not_held,
            entries_marked=entries_marked,
            titns_seeded=titns_seeded,
        )

    async def _resolve(self, book: ResolvableShelfBook) -> list[int]:
        """Resolve a book to held TITNs: ISBN first (precise), then title+author."""
        titns = await self._resolve_by_isbn(book)
        if titns:
            return titns
        return await self._resolve_by_title_author(book)

    async def _resolve_by_isbn(self, book: ResolvableShelfBook) -> list[int]:
        """Return the OPAC TITNs holding any of the book's ISBNs.

        Stops at the first ISBN that resolves (break-on-first-hit) — one held
        edition is enough to pull the book into the mirror, and it spares the OPAC
        the remaining lookups.
        """
        for isbn in book.isbn13:
            slice_ = await self._gateway.discover_slice(
                isbn_expert_expression(isbn),
                start_offset=0,
                max_results=self._max_results,
            )
            if slice_.titns:
                return _unique(slice_.titns)
        return []

    async def _resolve_by_title_author(self, book: ResolvableShelfBook) -> list[int]:
        """Fall back to a precise title+author expert query.

        Skipped when the book has no author (a title-only query is too broad to
        seed safely). The expression builder raises if the sanitised terms are
        empty, which we treat as "can't resolve".
        """
        if not book.author:
            return []
        try:
            expression = title_author_expert_expression(book.title, book.author)
        except ValueError:
            return []
        slice_ = await self._gateway.discover_slice(
            expression, start_offset=0, max_results=self._max_results
        )
        return _unique(slice_.titns)


def _unique(values: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
