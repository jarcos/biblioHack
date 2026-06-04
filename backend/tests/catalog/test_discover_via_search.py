"""Tests for the resumable novedades discovery use case (DiscoverViaExpertQuery)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bibliohack.catalog.application.ports import DiscoveryCursor, DiscoverySlice
from bibliohack.catalog.application.use_cases.discover_via_search import (
    DiscoverViaExpertQuery,
    novedades_expression,
)

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import (
        DiscoveryCursorRepository,
        OpacSearchGateway,
        ScrapeTaskRepository,
    )
    from bibliohack.catalog.domain.titn import Titn


class _StubSearchGateway:
    """Serves a fixed ordered result set, paginated by offset."""

    def __init__(self, titns: list[int]) -> None:
        self._all = titns
        self.calls: list[tuple[str, int, int]] = []  # (expression, start_offset, max_results)

    async def discover_titns(self, expression: str, *, max_results: int) -> list[int]:
        slice_ = await self.discover_slice(expression, start_offset=0, max_results=max_results)
        return slice_.titns

    async def discover_slice(
        self, expression: str, *, start_offset: int = 0, max_results: int
    ) -> DiscoverySlice:
        self.calls.append((expression, start_offset, max_results))
        window = self._all[start_offset : start_offset + max_results]
        return DiscoverySlice(
            titns=window, next_offset=start_offset + len(window), total=len(self._all)
        )


class _FakeTaskRepo:
    """Minimal seed_one tracker — already-known TITNs return False."""

    def __init__(self, known: set[int] | None = None) -> None:
        self.known = set(known or set())
        self.seeded: list[int] = []

    async def seed_one(self, titn: Titn) -> bool:
        value = int(titn)
        if value in self.known:
            return False
        self.known.add(value)
        self.seeded.append(value)
        return True


class _FakeCursorRepo:
    def __init__(self, initial: DiscoveryCursor | None = None) -> None:
        self._store: dict[str, DiscoveryCursor] = {}
        if initial:
            self._store[initial.expression] = initial

    async def get(self, expression: str) -> DiscoveryCursor | None:
        return self._store.get(expression)

    async def save(self, expression: str, *, next_offset: int, total: int | None) -> None:
        self._store[expression] = DiscoveryCursor(
            expression=expression, next_offset=next_offset, total=total
        )


def _use_case(
    gateway: _StubSearchGateway, repo: _FakeTaskRepo, cursors: _FakeCursorRepo
) -> DiscoverViaExpertQuery:
    return DiscoverViaExpertQuery(
        gateway=cast("OpacSearchGateway", gateway),
        tasks=cast("ScrapeTaskRepository", repo),
        cursors=cast("DiscoveryCursorRepository", cursors),
    )


def test_novedades_expression_since_year() -> None:
    assert novedades_expression(year_from=2024) == "(@fepu>=2024)"


def test_novedades_expression_bounded_range() -> None:
    assert novedades_expression(year_from=2020, year_to=2022) == "(@fepu>=2020) y (@fepu<=2022)"


async def test_first_run_starts_at_top_and_advances_cursor() -> None:
    gateway = _StubSearchGateway([1, 2, 3, 4, 5])
    repo = _FakeTaskRepo(known={2})
    cursors = _FakeCursorRepo()

    result = await _use_case(gateway, repo, cursors).execute("(@fepu>=2024)", max_results=3)

    assert gateway.calls == [("(@fepu>=2024)", 0, 3)]  # resumed from the top
    assert result.titns_found == 3
    assert result.seeded == 2  # 1 and 3 new; 2 known
    assert repo.seeded == [1, 3]
    assert result.start_offset == 0
    assert result.next_offset == 3
    assert result.total == 5
    saved = await cursors.get("(@fepu>=2024)")
    assert saved is not None
    assert saved.next_offset == 3


async def test_second_run_resumes_from_saved_cursor() -> None:
    gateway = _StubSearchGateway([1, 2, 3, 4, 5])
    repo = _FakeTaskRepo()
    cursors = _FakeCursorRepo(
        initial=DiscoveryCursor(expression="(@fepu>=2024)", next_offset=3, total=5)
    )

    result = await _use_case(gateway, repo, cursors).execute("(@fepu>=2024)", max_results=3)

    assert gateway.calls == [("(@fepu>=2024)", 3, 3)]  # jumped to offset 3
    assert repo.seeded == [4, 5]  # only the new slice
    assert result.next_offset == 5  # clamped at total
    saved = await cursors.get("(@fepu>=2024)")
    assert saved is not None
    assert saved.next_offset == 5


async def test_reset_ignores_saved_cursor() -> None:
    gateway = _StubSearchGateway([1, 2, 3, 4, 5])
    repo = _FakeTaskRepo()
    cursors = _FakeCursorRepo(
        initial=DiscoveryCursor(expression="(@fepu>=2024)", next_offset=3, total=5)
    )

    await _use_case(gateway, repo, cursors).execute("(@fepu>=2024)", max_results=2, reset=True)

    assert gateway.calls == [("(@fepu>=2024)", 0, 2)]  # restarted from the top
