"""Branch geocoding — Nominatim parse + EnrichBranchGeo sweep (pure, no network)."""

from __future__ import annotations

from dataclasses import dataclass

from bibliohack.holdings.application.use_cases.enrich_branch_geo import EnrichBranchGeo
from bibliohack.holdings.infrastructure.nominatim import parse_latlng

# --- parse_latlng ------------------------------------------------------------


def test_parse_latlng_reads_first_hit() -> None:
    assert parse_latlng([{"lat": "36.7497", "lon": "-3.0206"}]) == (36.7497, -3.0206)


def test_parse_latlng_empty_or_malformed_is_none() -> None:
    assert parse_latlng([]) is None
    assert parse_latlng([{"lat": "36.7"}]) is None  # missing lon
    assert parse_latlng([{"lat": "x", "lon": "y"}]) is None  # non-numeric


# --- EnrichBranchGeo sweep ---------------------------------------------------


@dataclass
class _Row:
    code: str
    municipality: str | None
    province: str | None


class _FakeRepo:
    """Serves ungeocoded rows once, records writes; geocoded rows drop out."""

    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows
        self.written: dict[str, tuple[float, float]] = {}

    async def iter_ungeocoded(self, *, limit: int, offset: int = 0) -> list[_Row]:
        remaining = [r for r in self._rows if r.code not in self.written]
        return remaining[offset : offset + limit]

    async def set_geo(self, code: str, *, lat: float, lng: float) -> None:
        self.written[code] = (lat, lng)


class _FakeGeocoder:
    """Returns a fixed coord for known municipalities; None otherwise."""

    def __init__(self, hits: dict[str, tuple[float, float]]) -> None:
        self._hits = hits
        self.calls: list[str] = []

    async def geocode(
        self, *, municipality: str, province: str | None = None
    ) -> tuple[float, float] | None:
        self.calls.append(municipality)
        return self._hits.get(municipality)


async def test_geocodes_hits_and_leaves_misses_for_retry() -> None:
    rows = [
        _Row("AL03", "Adra", "Almería"),
        _Row("AL04", "Berja", "Almería"),
        _Row("ZZ99", "Nowhere", None),
    ]
    repo = _FakeRepo(rows)
    geocoder = _FakeGeocoder({"Adra": (36.7497, -3.0206), "Berja": (36.85, -2.95)})
    stats = await EnrichBranchGeo(
        geocoder=geocoder, repository=repo, batch_size=10, pause_seconds=0.0
    ).execute()

    assert stats.scanned == 3
    assert stats.geocoded == 2
    assert stats.missed == 1
    assert repo.written == {"AL03": (36.7497, -3.0206), "AL04": (36.85, -2.95)}
    assert "Nowhere" not in repo.written


async def test_max_branches_caps_the_run() -> None:
    rows = [_Row(f"AL{i:02d}", f"Town{i}", "Almería") for i in range(10)]
    repo = _FakeRepo(rows)
    geocoder = _FakeGeocoder({f"Town{i}": (36.0 + i, -3.0) for i in range(10)})
    stats = await EnrichBranchGeo(
        geocoder=geocoder, repository=repo, batch_size=4, pause_seconds=0.0
    ).execute(max_branches=3)

    assert stats.scanned == 3
    assert stats.geocoded == 3


async def test_blank_municipality_counts_as_miss_without_calling_geocoder() -> None:
    repo = _FakeRepo([_Row("X1", None, "Almería")])
    geocoder = _FakeGeocoder({})
    stats = await EnrichBranchGeo(
        geocoder=geocoder, repository=repo, batch_size=10, pause_seconds=0.0
    ).execute()
    assert stats.missed == 1
    assert geocoder.calls == []  # None municipality short-circuits


async def test_commit_hook_fires_once_per_batch() -> None:
    rows = [_Row(f"AL{i:02d}", f"Town{i}", "Almería") for i in range(5)]
    repo = _FakeRepo(rows)
    geocoder = _FakeGeocoder({f"Town{i}": (36.0 + i, -3.0) for i in range(5)})
    commits = 0

    async def _commit() -> None:
        nonlocal commits
        commits += 1

    # batch_size=2 over 5 geocodable rows → batches of 2, 2, 1 → 3 commits.
    await EnrichBranchGeo(
        geocoder=geocoder,
        repository=repo,
        batch_size=2,
        pause_seconds=0.0,
        commit=_commit,
    ).execute()
    assert commits == 3
