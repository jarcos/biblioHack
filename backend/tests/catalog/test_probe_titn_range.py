"""Tests for the `ProbeTitnRange` use case.

We drive the use case with a `FakeGateway` whose responses are scripted by
"the OPAC has TITNs 1..N" — that lets us assert binary-search convergence
without ever touching a real OPAC or running Camoufox.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bibliohack.catalog.application.ports import (
    FetchOutcome,
    FetchResult,
)
from bibliohack.catalog.application.use_cases.probe_titn_range import ProbeTitnRange

if TYPE_CHECKING:
    from bibliohack.catalog.domain.titn import Titn


class FakeGateway:
    """Pretends to be an OPAC where TITN <= ``ceiling`` exist, minus optional gaps."""

    def __init__(self, *, ceiling: int, gaps: set[int] | None = None) -> None:
        self.ceiling = ceiling
        self.gaps = gaps or set()
        self.calls: list[int] = []

    async def fetch_record(self, titn: Titn) -> FetchResult:
        self.calls.append(int(titn))
        n = int(titn)
        exists = n <= self.ceiling and n not in self.gaps
        return FetchResult(
            titn=titn,
            outcome=FetchOutcome.OK if exists else FetchOutcome.NOT_FOUND,
            url=f"https://test/?TITN={n}",
            final_url=f"https://test/?TITN={n}",
            status_code=200,
            html=f"<html>TITN {n}</html>" if exists else "<html>not found</html>",
            latency_ms=1,
            bytes_in=10,
        )


# ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ceiling", [2000, 50_000, 1_234_567, 9_999_999])
async def test_probe_finds_the_exact_ceiling(ceiling: int) -> None:
    gateway = FakeGateway(ceiling=ceiling)
    use_case = ProbeTitnRange(gateway)  # type: ignore[arg-type]

    result = await use_case.execute()

    assert int(result.highest_existing) == ceiling
    assert result.lowest_missing is not None
    # `lowest_missing` is the first TITN at or above the true ceiling we
    # actually probed; gap-tolerant verification means it might be a few
    # above ceiling+1, but never below.
    assert int(result.lowest_missing) >= ceiling + 1
    # ~10 expansion calls + ~24 binary-search steps + ~10 gap-check probes
    # over a 10M-wide window stays comfortably under 50.
    assert result.fetches_used <= 50


async def test_probe_logarithmic_growth_phase() -> None:
    """The expansion phase quadruples, so the first calls climb fast."""
    gateway = FakeGateway(ceiling=1_000_000)
    use_case = ProbeTitnRange(gateway)  # type: ignore[arg-type]

    await use_case.execute()

    # First call is always TITN=1024 (initial cursor), then 4096, 16384, ...
    initial_climb = gateway.calls[:5]
    assert initial_climb == [1024, 4096, 16384, 65536, 262144]


async def test_probe_skips_a_single_record_gap() -> None:
    """A single-record gap (TITN=N missing, N+1 exists) must not terminate the
    search. This is the real-OPAC behaviour we discovered manually: TITN=16
    is missing but TITN=17 exists."""
    # Catalog goes up to 5_000_000 but has a gap at exactly TITN=1024,
    # which is our first expansion probe.
    gateway = FakeGateway(ceiling=5_000_000, gaps={1024})
    use_case = ProbeTitnRange(gateway)  # type: ignore[arg-type]

    result = await use_case.execute()

    # We must NOT terminate at TITN=1024 — the gap-tolerant probe sees that
    # TITN=1025 exists and treats the cluster as OK.
    assert int(result.highest_existing) == 5_000_000


async def test_probe_terminates_at_genuine_boundary_after_gap_check() -> None:
    """When the search hits the true upper bound, the gap-check exhausts and
    we correctly declare the boundary."""
    gateway = FakeGateway(ceiling=200)
    use_case = ProbeTitnRange(gateway)  # type: ignore[arg-type]

    result = await use_case.execute()

    assert int(result.highest_existing) == 200
    assert result.lowest_missing is not None
    # We probed 11 TITNs above 200 (offset 0..10) before declaring boundary.
    above_boundary_probes = [c for c in gateway.calls if c > 200]
    assert len(above_boundary_probes) >= 10


async def test_probe_stops_at_hard_max() -> None:
    """If we never find a missing TITN below hard_max, we stop and report."""
    gateway = FakeGateway(ceiling=10_000_000)  # all probed TITNs exist
    use_case = ProbeTitnRange(gateway, hard_max=2000)  # type: ignore[arg-type]

    result = await use_case.execute()

    assert result.lowest_missing is None
    # We expanded to 1024 (initial cursor); 4096 > 2000 so loop terminates;
    # we then probe hard_max=2000 itself as the defensive bracket attempt.
    assert int(result.highest_existing) >= 1024
    assert all(c <= 2000 for c in gateway.calls)


async def test_probe_zero_hard_max_rejected() -> None:
    gateway = FakeGateway(ceiling=10)
    with pytest.raises(ValueError, match="hard_max must be at least 2"):
        ProbeTitnRange(gateway, hard_max=1)  # type: ignore[arg-type]


async def test_on_probe_callback_invoked_per_fetch() -> None:
    gateway = FakeGateway(ceiling=100)
    observed: list[tuple[int, str]] = []

    async def callback(titn: Titn, result: FetchResult) -> None:
        observed.append((int(titn), result.outcome.value))

    use_case = ProbeTitnRange(gateway, on_probe=callback)  # type: ignore[arg-type]
    await use_case.execute()

    assert len(observed) == len(gateway.calls)
    # Every observed entry matches the gateway's call sequence.
    assert [t for t, _ in observed] == gateway.calls


async def test_sync_on_probe_callback_also_works() -> None:
    """The hook accepts a sync callable too — handy for typer's echo."""
    gateway = FakeGateway(ceiling=100)
    counter = [0]

    def sync_callback(titn: Titn, result: FetchResult) -> None:
        counter[0] += 1

    use_case = ProbeTitnRange(gateway, on_probe=sync_callback)  # type: ignore[arg-type]
    await use_case.execute()

    assert counter[0] == len(gateway.calls)
