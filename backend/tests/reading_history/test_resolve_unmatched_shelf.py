"""Unit tests for ResolveUnmatchedShelf — ISBN/title resolve, held/not_held, bounds.

Mirrors the canon C3 resolve tests, with fakes for the OPAC gateway, the shelf
repository (serves resolvable books, records resolve outcomes), and the scrape-task
seeder. The repository fake drops a book out of the resolvable pool once its outcome
is recorded, so the use case's batch loop terminates exactly as it does in Postgres.
"""

from __future__ import annotations

import pytest

from bibliohack.catalog.application.ports import DiscoverySlice
from bibliohack.catalog.application.use_cases.discover_via_search import (
    isbn_expert_expression,
    title_author_expert_expression,
)
from bibliohack.reading_history.application.ports import ResolvableShelfBook
from bibliohack.reading_history.application.use_cases.resolve_unmatched_shelf import (
    ResolveUnmatchedShelf,
)
from bibliohack.reading_history.domain.shelf import ShelfResolveStatus

pytestmark = pytest.mark.asyncio


class _FakeGateway:
    """Maps an expert expression to the TITNs the OPAC 'holds'; records queries."""

    def __init__(self, holdings: dict[str, list[int]]) -> None:
        self._holdings = holdings
        self.queried: list[str] = []

    async def discover_titns(self, expression: str, *, max_results: int) -> list[int]:
        slice_ = await self.discover_slice(expression, start_offset=0, max_results=max_results)
        return slice_.titns

    async def discover_slice(
        self, expression: str, *, start_offset: int = 0, max_results: int
    ) -> DiscoverySlice:
        self.queried.append(expression)
        titns = self._holdings.get(expression, [])[:max_results]
        return DiscoverySlice(titns=titns, next_offset=len(titns), total=len(titns))


class _FakeRepo:
    """Serves resolvable books; recording an outcome removes it from the pool."""

    def __init__(self, books: list[ResolvableShelfBook]) -> None:
        self._pool = list(books)
        self.marked: dict[str, ShelfResolveStatus] = {}

    async def iter_resolvable_books(
        self, *, limit: int, cooldown_days: int
    ) -> list[ResolvableShelfBook]:
        return self._pool[:limit]

    async def mark_resolve_result(self, entry_ids, status: ShelfResolveStatus) -> None:
        ids = set(entry_ids)
        for entry_id in ids:
            self.marked[entry_id] = status
        self._pool = [b for b in self._pool if not ids.intersection(b.entry_ids)]


class _FakeTasks:
    def __init__(self, known: set[int] | None = None) -> None:
        self.known = set(known or set())
        self.seeded: list[int] = []

    async def seed_one(self, titn) -> bool:
        value = int(titn)
        self.seeded.append(value)
        if value in self.known:
            return False
        self.known.add(value)
        return True


def _book(
    *entry_ids: str, title: str = "T", author: str | None = "A", isbn13: tuple[str, ...] = ()
) -> ResolvableShelfBook:
    return ResolvableShelfBook(
        entry_ids=tuple(entry_ids), title=title, author=author, isbn13=isbn13
    )


async def test_isbn_hit_seeds_titn_and_marks_held() -> None:
    isbn = "9788497934329"
    gw = _FakeGateway({isbn_expert_expression(isbn): [111]})
    repo = _FakeRepo([_book("e1", isbn13=(isbn,))])
    tasks = _FakeTasks()

    stats = await ResolveUnmatchedShelf(gateway=gw, repository=repo, tasks=tasks).execute()

    assert stats.held == 1
    assert stats.not_held == 0
    assert stats.titns_seeded == 1
    assert tasks.seeded == [111]
    assert repo.marked == {"e1": ShelfResolveStatus.HELD}


async def test_break_on_first_isbn_hit() -> None:
    isbn_a, isbn_b = "1111111111111", "2222222222222"
    gw = _FakeGateway({isbn_expert_expression(isbn_a): [7]})  # b never holds
    repo = _FakeRepo([_book("e1", isbn13=(isbn_a, isbn_b))])

    await ResolveUnmatchedShelf(gateway=gw, repository=repo, tasks=_FakeTasks()).execute()

    # Stopped after the first ISBN resolved — second ISBN never queried.
    assert gw.queried == [isbn_expert_expression(isbn_a)]


async def test_title_author_fallback_when_no_isbn() -> None:
    expr = title_author_expert_expression("Rayuela", "Cortázar")
    gw = _FakeGateway({expr: [222]})
    repo = _FakeRepo([_book("e1", title="Rayuela", author="Cortázar", isbn13=())])
    tasks = _FakeTasks()

    stats = await ResolveUnmatchedShelf(gateway=gw, repository=repo, tasks=tasks).execute()

    assert stats.held == 1
    assert tasks.seeded == [222]


async def test_no_author_skips_title_fallback_and_marks_not_held() -> None:
    gw = _FakeGateway({})
    repo = _FakeRepo([_book("e1", title="Untitled", author=None, isbn13=())])

    stats = await ResolveUnmatchedShelf(gateway=gw, repository=repo, tasks=_FakeTasks()).execute()

    assert gw.queried == []  # no ISBN, no author → nothing queried
    assert stats.not_held == 1
    assert repo.marked == {"e1": ShelfResolveStatus.NOT_HELD}


async def test_dedup_one_query_marks_all_entries_in_group() -> None:
    isbn = "9788497934329"
    gw = _FakeGateway({isbn_expert_expression(isbn): [333]})
    # Three users, same book → one group, one OPAC query, three entries marked.
    repo = _FakeRepo([_book("u1", "u2", "u3", isbn13=(isbn,))])
    tasks = _FakeTasks()

    stats = await ResolveUnmatchedShelf(gateway=gw, repository=repo, tasks=tasks).execute()

    assert gw.queried == [isbn_expert_expression(isbn)]
    assert stats.held == 1  # one book
    assert stats.entries_marked == 3  # three shelf entries
    assert repo.marked == {
        "u1": ShelfResolveStatus.HELD,
        "u2": ShelfResolveStatus.HELD,
        "u3": ShelfResolveStatus.HELD,
    }


async def test_miss_marks_not_held_and_seeds_nothing() -> None:
    gw = _FakeGateway({})  # OPAC holds nothing
    repo = _FakeRepo([_book("e1", title="Nope", author="Nobody", isbn13=("9999999999999",))])
    tasks = _FakeTasks()

    stats = await ResolveUnmatchedShelf(gateway=gw, repository=repo, tasks=tasks).execute()

    assert stats.not_held == 1
    assert tasks.seeded == []
    assert repo.marked == {"e1": ShelfResolveStatus.NOT_HELD}


async def test_max_rows_bounds_books_scanned() -> None:
    gw = _FakeGateway({})
    repo = _FakeRepo([_book(f"e{i}", title=f"T{i}", author="A") for i in range(5)])

    stats = await ResolveUnmatchedShelf(
        gateway=gw, repository=repo, tasks=_FakeTasks(), batch_size=10
    ).execute(max_rows=2)

    assert stats.scanned == 2
