"""SeedBacklistChunk — resumably enumerate the TITN space for the backlist crawl.

M7 (network-wide backlist crawl, see `docs/design/m7-backlist-crawl.md`) is a
**coverage** job: the ongoing novedades discovery only seeds `@fepu>=2024`, so
the pre-2024 backlist — in every province — is only as complete as the one-time
bootstrap TITN sweep got. This use case closes the gap by walking the whole TITN
space in resumable chunks and seeding each chunk as `discovered` at a **lower
priority** than novedades, so the existing worker drains fresh records first and
fills only its idle capacity with the backlist (freshness is never starved).

Resumability reuses the `discovery_cursors` table under a reserved sentinel
expression (`__backlist_titn__`): `next_offset` holds the next TITN to seed and
`total` the probed high-water mark. (Semantic note: here `next_offset` is a
TITN, not a DOC search offset — the schema, `(next_offset:int, total:int)`,
fits either reading.)

Two modes:

- **fixed chunk** — seed `chunk_size` TITNs each run (relies on `seed_range`
  idempotency; lets the discovered backlog grow unbounded).
- **top-up** (pass `target_depth`) — seed only enough to refill the queue of
  outstanding backlist rows to `target_depth`, keeping the discovered backlog
  bounded and the claim index cheap. Recommended for the crawler-plane cron.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from bibliohack.catalog.domain.titn import Titn

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import (
        DiscoveryCursorRepository,
        ScrapeTaskRepository,
    )
    from bibliohack.catalog.application.use_cases.probe_titn_range import ProbeResult

# Reserved discovery_cursors key for the backlist TITN sweep.
BACKLIST_CURSOR_KEY = "__backlist_titn__"

# Claim precedence for backlist rows: higher number = lower precedence than the
# default 100 used by novedades/refresh (the worker claims `priority ASC`).
BACKLIST_PRIORITY = 500


class TitnRangeProbe(Protocol):
    """The subset of `ProbeTitnRange` this use case needs (one polite probe)."""

    async def execute(self) -> ProbeResult: ...


@dataclass(frozen=True, slots=True)
class BacklistResult:
    """Outcome of one backlist seeding run."""

    seeded: int  # NEW rows inserted this run (already-known TITNs don't count)
    range_low: int | None  # first TITN seeded this run (None if nothing seeded)
    range_high: int | None  # last TITN seeded this run
    next_offset: int  # next TITN a future run will resume from
    total: int  # probed high-water mark of the TITN space
    queue_depth: int  # outstanding backlist `discovered` rows after this run
    probed: bool  # whether this run ran a fresh range probe
    done: bool  # whether the whole TITN space has now been seeded


class SeedBacklistChunk:
    """Use case: seed the next chunk of the TITN backlist, resumably."""

    def __init__(
        self,
        *,
        probe: TitnRangeProbe,
        tasks: ScrapeTaskRepository,
        cursors: DiscoveryCursorRepository,
        priority: int = BACKLIST_PRIORITY,
    ) -> None:
        self._probe = probe
        self._tasks = tasks
        self._cursors = cursors
        self._priority = priority

    async def execute(
        self,
        *,
        chunk_size: int,
        target_depth: int | None = None,
        reset: bool = False,
    ) -> BacklistResult:
        if chunk_size <= 0:
            msg = f"chunk_size must be positive, got {chunk_size}"
            raise ValueError(msg)

        cursor = None if reset else await self._cursors.get(BACKLIST_CURSOR_KEY)

        # First run (or --reset, or a cursor that never recorded a total):
        # establish the high-water mark with one polite probe and start at 1.
        probed = False
        if cursor is None or cursor.total is None:
            result = await self._probe.execute()
            total = int(result.highest_existing)
            next_titn = 1
            probed = True
        else:
            total = cursor.total
            next_titn = max(1, cursor.next_offset)

        # Already swept the whole space — nothing left to seed.
        if next_titn > total:
            depth = await self._tasks.count_discovered_with_priority(self._priority)
            await self._cursors.save(BACKLIST_CURSOR_KEY, next_offset=next_titn, total=total)
            return BacklistResult(
                seeded=0,
                range_low=None,
                range_high=None,
                next_offset=next_titn,
                total=total,
                queue_depth=depth,
                probed=probed,
                done=True,
            )

        # How many TITNs to seed this run.
        n = chunk_size
        if target_depth is not None:
            depth_before = await self._tasks.count_discovered_with_priority(self._priority)
            budget = max(0, target_depth - depth_before)
            n = min(chunk_size, budget)

        # Queue already at/above target depth — advance nothing, seed nothing.
        if n <= 0:
            depth = await self._tasks.count_discovered_with_priority(self._priority)
            return BacklistResult(
                seeded=0,
                range_low=None,
                range_high=None,
                next_offset=next_titn,
                total=total,
                queue_depth=depth,
                probed=probed,
                done=False,
            )

        low = next_titn
        high = min(next_titn + n - 1, total)
        seeded = await self._tasks.seed_range(Titn(low), Titn(high), priority=self._priority)
        new_next = high + 1
        await self._cursors.save(BACKLIST_CURSOR_KEY, next_offset=new_next, total=total)

        depth = await self._tasks.count_discovered_with_priority(self._priority)
        return BacklistResult(
            seeded=seeded,
            range_low=low,
            range_high=high,
            next_offset=new_next,
            total=total,
            queue_depth=depth,
            probed=probed,
            done=new_next > total,
        )
