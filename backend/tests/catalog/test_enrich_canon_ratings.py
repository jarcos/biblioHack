"""EnrichCanonRatings (C4) — store OL counts, retry failures, bounded sweep."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.catalog.application.ports import CanonSeedRow
from bibliohack.catalog.application.use_cases.enrich_canon_ratings import EnrichCanonRatings

if TYPE_CHECKING:
    from collections.abc import Sequence


class _FakeSource:
    """Maps an ISBN to a count, or to None (lookup failed)."""

    def __init__(self, counts: dict[str, int | None]) -> None:
        self._counts = counts
        self.calls: list[str] = []

    async def fetch_rating_count(self, isbn: str) -> int | None:
        self.calls.append(isbn)
        return self._counts.get(isbn)


class _FakeRepo:
    """Unrated pool; set_rating_count removes a row (it's now rated)."""

    def __init__(self, rows: list[CanonSeedRow]) -> None:
        self._pool = {r.id: r for r in rows}
        self.counts: dict[str, int] = {}

    async def iter_unrated(self, *, limit: int, offset: int = 0) -> Sequence[CanonSeedRow]:
        return list(self._pool.values())[offset : offset + limit]

    async def set_rating_count(self, seed_id: str, count: int) -> None:
        self.counts[seed_id] = count
        self._pool.pop(seed_id, None)


def _row(seed_id: str, isbn: str) -> CanonSeedRow:
    return CanonSeedRow(id=seed_id, title=f"T{seed_id}", author=None, isbn13=(isbn,))


def _use_case(source: object, repo: object, **kw: object) -> EnrichCanonRatings:
    from typing import cast

    from bibliohack.catalog.application.ports import CanonRatingsSource, CanonSeedRepository

    return EnrichCanonRatings(
        source=cast("CanonRatingsSource", source),
        repository=cast("CanonSeedRepository", repo),
        **kw,  # type: ignore[arg-type]
    )


async def test_stores_counts_including_zero() -> None:
    repo = _FakeRepo([_row("s1", "111"), _row("s2", "222")])
    source = _FakeSource({"111": 7, "222": 0})

    stats = await _use_case(source, repo).execute()

    assert stats.rated == 2
    assert stats.with_ratings == 1  # only s1 had > 0
    assert repo.counts == {"s1": 7, "s2": 0}


async def test_failed_lookup_is_left_for_retry_and_terminates() -> None:
    # A None (failed) lookup must not be recorded, and must not loop forever.
    repo = _FakeRepo([_row("s1", "111")])
    source = _FakeSource({"111": None})

    stats = await _use_case(source, repo, batch_size=10).execute()

    assert stats.failed == 1
    assert stats.rated == 0
    assert "s1" not in repo.counts  # left NULL
    assert source.calls == ["111"]  # queried exactly once (no re-read loop)


async def test_mixed_batch_pages_past_failures() -> None:
    rows = [_row("s0", "0"), _row("s1", "1"), _row("s2", "2")]
    repo = _FakeRepo(rows)
    source = _FakeSource({"0": 5, "1": None, "2": 3})

    stats = await _use_case(source, repo, batch_size=10).execute()

    assert stats.scanned == 3
    assert stats.rated == 2
    assert stats.failed == 1
    assert repo.counts == {"s0": 5, "s2": 3}


async def test_max_rows_bounds_the_run() -> None:
    rows = [_row(f"s{i}", str(i)) for i in range(5)]
    repo = _FakeRepo(rows)
    source = _FakeSource({str(i): i for i in range(5)})

    stats = await _use_case(source, repo, batch_size=2).execute(max_rows=3)

    assert stats.scanned == 3
