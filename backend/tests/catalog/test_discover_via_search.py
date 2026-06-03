"""Tests for the novedades discovery use case (DiscoverViaExpertQuery)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bibliohack.catalog.application.use_cases.discover_via_search import (
    DiscoverViaExpertQuery,
    novedades_expression,
)

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import OpacSearchGateway, ScrapeTaskRepository
    from bibliohack.catalog.domain.titn import Titn


class _StubSearchGateway:
    """Returns a fixed TITN list; records the call args."""

    def __init__(self, titns: list[int]) -> None:
        self._titns = titns
        self.calls: list[tuple[str, int]] = []

    async def discover_titns(self, expression: str, *, max_results: int) -> list[int]:
        self.calls.append((expression, max_results))
        return self._titns[:max_results]


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


def test_novedades_expression_since_year() -> None:
    assert novedades_expression(year_from=2024) == "(@fepu>=2024)"


def test_novedades_expression_bounded_range() -> None:
    assert novedades_expression(year_from=2020, year_to=2022) == "(@fepu>=2020) y (@fepu<=2022)"


async def test_discover_seeds_only_new_titns() -> None:
    gateway = _StubSearchGateway([1, 2, 3])
    repo = _FakeTaskRepo(known={2})  # TITN 2 already in scrape_tasks
    use_case = DiscoverViaExpertQuery(
        gateway=cast("OpacSearchGateway", gateway),
        tasks=cast("ScrapeTaskRepository", repo),
    )

    result = await use_case.execute("(@fepu>=2024)", max_results=10)

    assert result.titns_found == 3
    assert result.seeded == 2  # 1 and 3 are new; 2 was already known
    assert repo.seeded == [1, 3]
    assert gateway.calls == [("(@fepu>=2024)", 10)]
