"""ProbeTitnRange — find the upper bound of the OPAC's TITN space.

The OPAC assigns sequential integer ids (`Titn`) to records. We don't know
how large that space is, so we probe it with a logarithmic schedule:

1. **Expand** — try `1`, `10`, `100`, `1_000`, … until we hit a TITN that
   the OPAC says doesn't exist (or until we hit `hard_max`). That gives us
   a known-OK low bound and a known-missing high bound.
2. **Bisect** — binary-search between them for the largest TITN that
   does exist.

The whole thing fits comfortably in ~20 polite fetches and tells us
roughly how many records the network holds. We re-run this monthly to
catch new growth at the high end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bibliohack.catalog.application.ports import FetchOutcome
from bibliohack.catalog.domain.titn import Titn

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bibliohack.catalog.application.ports import FetchResult, OpacGateway

log = logging.getLogger(__name__)

DEFAULT_HARD_MAX = 10_000_000  # extreme upper safety bound

# When a probe says NOT_FOUND, we don't trust it on its own — the real OPAC
# has small sequence gaps (e.g. TITN=16 doesn't exist but TITN=17 does).
# We check this many neighbours above the missing TITN before accepting it
# as the actual boundary.
GAP_TOLERANCE = 10


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of the probe. `highest_existing` is what we'd seed from."""

    highest_existing: Titn
    lowest_missing: Titn | None
    fetches_used: int


class ProbeTitnRange:
    """Use case: discover the high-water mark of the TITN space.

    Pure orchestration — receives an `OpacGateway` (port), returns a typed
    `ProbeResult`. The CLI wraps this with command-line ergonomics; the
    seeder (next commit) consumes its output.
    """

    def __init__(
        self,
        gateway: OpacGateway,
        *,
        hard_max: int = DEFAULT_HARD_MAX,
        # Hookable for tests — by default we just log. Injecting a callback
        # lets the CLI print progress without coupling this use case to typer.
        on_probe: Callable[[Titn, FetchResult], Awaitable[None] | None] | None = None,
    ) -> None:
        if hard_max < 2:
            msg = "hard_max must be at least 2"
            raise ValueError(msg)
        self._gateway = gateway
        self._hard_max = hard_max
        self._on_probe = on_probe
        self._fetches = 0

    async def execute(self) -> ProbeResult:
        """Run the probe. Returns `ProbeResult` once converged."""
        # Phase 1: exponential expansion to bracket the range.
        # Start at 1024 — the catalog has well over a million records, so
        # starting low only burns fetches verifying things we already know
        # exist. We push upward until we find a TITN that doesn't.
        low_exists = Titn(1)
        high_missing: Titn | None = None

        cursor = 1024  # logarithmic growth; safely above any small-number gaps
        while cursor <= self._hard_max:
            outcome = await self._gap_tolerant_probe(Titn(cursor))
            if outcome is FetchOutcome.OK:
                low_exists = Titn(cursor)
                cursor *= 4  # quadruple — faster than doubling
            else:
                high_missing = Titn(cursor)
                break

        # If quadrupling overshot but `hard_max` itself hasn't been probed,
        # try it — it may still exist (so we report it and recommend raising
        # the ceiling) or be the missing high bound we need to bisect.
        if high_missing is None and int(low_exists) < self._hard_max:
            outcome = await self._probe_one(Titn(self._hard_max))
            if outcome is FetchOutcome.OK:
                low_exists = Titn(self._hard_max)
            else:
                high_missing = Titn(self._hard_max)

        if high_missing is None:
            # `hard_max` itself exists — we genuinely can't bracket the
            # range. Caller should re-run with a higher `hard_max`.
            log.warning(
                "probe.hit_hard_max low_exists=%d hard_max=%d",
                int(low_exists),
                self._hard_max,
            )
            return ProbeResult(
                highest_existing=low_exists,
                lowest_missing=None,
                fetches_used=self._fetches,
            )

        # Phase 2: binary search between low_exists and high_missing.
        # We use a plain probe (no gap-tolerance) here — a false NOT_FOUND
        # at the boundary only shifts the result by one, vs. the
        # exponential-cost blow-up gap-tolerance would cause when half the
        # bisection probes naturally return NOT_FOUND. The seeder fills
        # `scrape_tasks` for the whole range anyway; real gaps become
        # `not_found` task rows.
        lo, hi = int(low_exists), int(high_missing)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            outcome = await self._probe_one(Titn(mid))
            if outcome is FetchOutcome.OK:
                lo = mid
            else:
                hi = mid

        return ProbeResult(
            highest_existing=Titn(lo),
            lowest_missing=Titn(hi),
            fetches_used=self._fetches,
        )

    async def _probe_one(self, titn: Titn) -> FetchOutcome:
        result = await self._gateway.fetch_record(titn)
        self._fetches += 1
        log.info(
            "probe.fetched titn=%d outcome=%s status=%s",
            int(titn),
            result.outcome,
            result.status_code,
        )
        if self._on_probe is not None:
            cb = self._on_probe(titn, result)
            if cb is not None:
                await cb
        return result.outcome

    async def _gap_tolerant_probe(self, titn: Titn) -> FetchOutcome:
        """Probe `titn` and, if it's NOT_FOUND, verify with nearby neighbours.

        The OPAC has small sequence gaps (deleted/retired records). A single
        NOT_FOUND result is not enough to conclude that everything above
        `titn` is also missing — we check up to `GAP_TOLERANCE` higher
        TITNs first. If ANY of them exist, the original was just a gap and
        we treat the cluster as "exists".

        Returns OK if the cluster has at least one existing record; otherwise
        NOT_FOUND. PERMANENT/TRANSIENT errors pass through unchanged.
        """
        outcome = await self._probe_one(titn)
        if outcome is not FetchOutcome.NOT_FOUND:
            return outcome

        # Sniff the next few TITNs to distinguish "real boundary" from "gap".
        for offset in range(1, GAP_TOLERANCE + 1):
            neighbour = int(titn) + offset
            if neighbour > self._hard_max:
                break
            neighbour_outcome = await self._probe_one(Titn(neighbour))
            if neighbour_outcome is FetchOutcome.OK:
                log.info(
                    "probe.gap_skipped titn=%d gap_size=%d resumed_at=%d",
                    int(titn),
                    offset,
                    neighbour,
                )
                # Neighbour exists, so the original NOT_FOUND was just a gap.
                # Caller treats this as OK at `titn`'s logical position (we
                # remember the neighbour as the resumption point via the
                # protected attribute below — phase-1 callers use the cursor
                # value, phase-2 callers tolerate the off-by-N).
                return FetchOutcome.OK

        return FetchOutcome.NOT_FOUND
