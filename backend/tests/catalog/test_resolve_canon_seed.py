"""ResolveCanonSeed (C3) — ISBN resolve, held/not_held, politeness, bounds."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.catalog.application.ports import CanonSeedRow, DiscoverySlice
from bibliohack.catalog.application.use_cases.discover_via_search import (
    isbn_expert_expression,
)
from bibliohack.catalog.application.use_cases.resolve_canon_seed import ResolveCanonSeed
from bibliohack.catalog.domain.canon import AcquireStatus

if TYPE_CHECKING:
    from bibliohack.catalog.domain.titn import Titn


class _FakeGateway:
    """Maps an ISBN expert expression to the TITNs the OPAC 'holds'.

    Records every expression queried so tests can assert break-on-first-hit.
    """

    def __init__(self, holdings: dict[str, list[int]]) -> None:
        self._holdings = holdings  # expression -> titns
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
    """Holds resolvable rows; set_acquire_status moves a row out of the pool."""

    def __init__(self, rows: list[CanonSeedRow]) -> None:
        self._pool = {r.id: r for r in rows}
        self.status: dict[str, AcquireStatus] = {}

    async def iter_resolvable(self, *, limit: int) -> list[CanonSeedRow]:
        return list(self._pool.values())[:limit]

    async def set_acquire_status(self, seed_id: str, status: AcquireStatus) -> None:
        self.status[seed_id] = status
        self._pool.pop(seed_id, None)


class _FakeTasks:
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


def _row(seed_id: str, isbns: tuple[str, ...]) -> CanonSeedRow:
    return CanonSeedRow(id=seed_id, title=f"T{seed_id}", author=None, isbn13=isbns)


def _use_case(gateway: object, repo: object, tasks: object, **kw: object) -> ResolveCanonSeed:
    from typing import cast

    from bibliohack.catalog.application.ports import (
        CanonSeedRepository,
        OpacSearchGateway,
        ScrapeTaskRepository,
    )

    return ResolveCanonSeed(
        gateway=cast("OpacSearchGateway", gateway),
        repository=cast("CanonSeedRepository", repo),
        tasks=cast("ScrapeTaskRepository", tasks),
        **kw,  # type: ignore[arg-type]
    )


async def test_isbn_hit_marks_held_and_seeds_titns() -> None:
    isbn = "9788439732471"
    gateway = _FakeGateway({isbn_expert_expression(isbn): [555, 556]})
    repo = _FakeRepo([_row("s1", (isbn,))])
    tasks = _FakeTasks()

    stats = await _use_case(gateway, repo, tasks).execute()

    assert stats.held == 1
    assert stats.not_held == 0
    assert stats.titns_seeded == 2
    assert tasks.seeded == [555, 556]
    assert repo.status["s1"] is AcquireStatus.HELD


async def test_isbn_miss_marks_not_held_and_seeds_nothing() -> None:
    gateway = _FakeGateway({})  # OPAC holds nothing
    repo = _FakeRepo([_row("s1", ("9780000000001",))])
    tasks = _FakeTasks()

    stats = await _use_case(gateway, repo, tasks).execute()

    assert stats.not_held == 1
    assert stats.held == 0
    assert tasks.seeded == []
    assert repo.status["s1"] is AcquireStatus.NOT_HELD


async def test_breaks_on_first_isbn_that_resolves() -> None:
    hit, second = "9788439732471", "9780000000002"
    gateway = _FakeGateway({isbn_expert_expression(hit): [1]})
    repo = _FakeRepo([_row("s1", (hit, second))])

    await _use_case(gateway, repo, _FakeTasks()).execute()

    # Only the first ISBN was queried — the second is never hit.
    assert gateway.queried == [isbn_expert_expression(hit)]


async def test_tries_next_isbn_when_first_misses() -> None:
    first, hit = "9780000000001", "9788439732471"
    gateway = _FakeGateway({isbn_expert_expression(hit): [42]})
    repo = _FakeRepo([_row("s1", (first, hit))])
    tasks = _FakeTasks()

    stats = await _use_case(gateway, repo, tasks).execute()

    assert gateway.queried == [isbn_expert_expression(first), isbn_expert_expression(hit)]
    assert stats.held == 1
    assert tasks.seeded == [42]


async def test_max_rows_bounds_the_run() -> None:
    rows = [_row(f"s{i}", (f"978000000000{i}",)) for i in range(5)]
    gateway = _FakeGateway({})
    repo = _FakeRepo(rows)

    stats = await _use_case(gateway, repo, _FakeTasks(), batch_size=2).execute(max_rows=3)

    assert stats.scanned == 3
    assert stats.checked == 3
