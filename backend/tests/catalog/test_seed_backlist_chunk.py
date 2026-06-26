"""Tests for the resumable backlist TITN sweep use case (SeedBacklistChunk)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from bibliohack.catalog.application.ports import DiscoveryCursor
from bibliohack.catalog.application.use_cases.probe_titn_range import ProbeResult
from bibliohack.catalog.application.use_cases.seed_backlist_chunk import (
    BACKLIST_CURSOR_KEY,
    BACKLIST_PRIORITY,
    SeedBacklistChunk,
)
from bibliohack.catalog.domain.titn import Titn

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import (
        DiscoveryCursorRepository,
        ScrapeTaskRepository,
    )


class _FakeProbe:
    """Returns a fixed high-water mark and counts how often it's called."""

    def __init__(self, highest: int) -> None:
        self._highest = highest
        self.calls = 0

    async def execute(self) -> ProbeResult:
        self.calls += 1
        return ProbeResult(
            highest_existing=Titn(self._highest), lowest_missing=None, fetches_used=1
        )


class _FakeTaskRepo:
    """Tracks seeded TITNs + their priority; models seed_range idempotency."""

    def __init__(self, known: set[int] | None = None) -> None:
        self.known: set[int] = set(known or set())
        self.priority_of: dict[int, int] = {}
        self.seed_calls: list[tuple[int, int, int]] = []  # (low, high, priority)

    async def seed_range(self, low: Titn, high: Titn, *, priority: int = 100) -> int:
        self.seed_calls.append((int(low), int(high), priority))
        inserted = 0
        for t in range(int(low), int(high) + 1):
            if t not in self.known:
                self.known.add(t)
                self.priority_of[t] = priority
                inserted += 1
        return inserted

    async def count_discovered_with_priority(self, priority: int) -> int:
        return sum(1 for p in self.priority_of.values() if p == priority)


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
    probe: _FakeProbe,
    tasks: _FakeTaskRepo,
    cursors: _FakeCursorRepo,
) -> SeedBacklistChunk:
    return SeedBacklistChunk(
        probe=probe,  # structurally satisfies TitnRangeProbe
        tasks=cast("ScrapeTaskRepository", tasks),
        cursors=cast("DiscoveryCursorRepository", cursors),
    )


async def test_first_run_probes_and_seeds_from_one() -> None:
    probe, tasks, cursors = _FakeProbe(highest=1000), _FakeTaskRepo(), _FakeCursorRepo()
    uc = _use_case(probe, tasks, cursors)

    result = await uc.execute(chunk_size=100)

    assert probe.calls == 1
    assert result.probed is True
    assert result.range_low == 1
    assert result.range_high == 100
    assert result.seeded == 100
    assert result.next_offset == 101
    assert result.total == 1000
    assert result.done is False
    # All seeded rows carry the backlist priority, not the default 100.
    assert tasks.seed_calls == [(1, 100, BACKLIST_PRIORITY)]
    # Cursor persisted for the next run.
    saved = await cursors.get(BACKLIST_CURSOR_KEY)
    assert saved is not None
    assert saved.next_offset == 101
    assert saved.total == 1000


async def test_resumes_from_saved_cursor_without_reprobing() -> None:
    probe = _FakeProbe(highest=1000)
    tasks = _FakeTaskRepo()
    cursors = _FakeCursorRepo(
        DiscoveryCursor(expression=BACKLIST_CURSOR_KEY, next_offset=101, total=1000)
    )
    uc = _use_case(probe, tasks, cursors)

    result = await uc.execute(chunk_size=100)

    assert probe.calls == 0  # total already known → no re-probe
    assert result.probed is False
    assert result.range_low == 101
    assert result.range_high == 200
    assert result.next_offset == 201


async def test_final_chunk_clamps_to_total_and_marks_done() -> None:
    probe = _FakeProbe(highest=150)
    tasks = _FakeTaskRepo()
    cursors = _FakeCursorRepo(
        DiscoveryCursor(expression=BACKLIST_CURSOR_KEY, next_offset=101, total=150)
    )
    uc = _use_case(probe, tasks, cursors)

    result = await uc.execute(chunk_size=100)

    assert result.range_high == 150  # clamped, not 200
    assert result.seeded == 50
    assert result.next_offset == 151
    assert result.done is True


async def test_when_already_swept_seeds_nothing_and_is_done() -> None:
    probe = _FakeProbe(highest=150)
    tasks = _FakeTaskRepo()
    cursors = _FakeCursorRepo(
        DiscoveryCursor(expression=BACKLIST_CURSOR_KEY, next_offset=151, total=150)
    )
    uc = _use_case(probe, tasks, cursors)

    result = await uc.execute(chunk_size=100)

    assert result.seeded == 0
    assert result.done is True
    assert tasks.seed_calls == []


async def test_idempotent_rerun_seeds_only_unknown_titns() -> None:
    probe = _FakeProbe(highest=1000)
    tasks = _FakeTaskRepo(known={1, 2, 3})  # 1..3 already seeded (e.g. by bootstrap)
    cursors = _FakeCursorRepo()
    uc = _use_case(probe, tasks, cursors)

    result = await uc.execute(chunk_size=10)

    assert result.range_low == 1
    assert result.range_high == 10
    assert result.seeded == 7  # 1..3 already known


async def test_topup_seeds_only_up_to_target_depth() -> None:
    probe = _FakeProbe(highest=10_000)
    tasks = _FakeTaskRepo()
    cursors = _FakeCursorRepo()
    uc = _use_case(probe, tasks, cursors)

    # Empty queue, target 100 → seed exactly 100 even though chunk allows 1000.
    result = await uc.execute(chunk_size=1000, target_depth=100)
    assert result.seeded == 100
    assert result.range_high == 100
    assert result.queue_depth == 100


async def test_topup_seeds_nothing_when_queue_already_full() -> None:
    probe = _FakeProbe(highest=10_000)
    # 100 backlist rows already queued at BACKLIST_PRIORITY.
    tasks = _FakeTaskRepo()
    for t in range(1, 101):
        tasks.known.add(t)
        tasks.priority_of[t] = BACKLIST_PRIORITY
    cursors = _FakeCursorRepo(
        DiscoveryCursor(expression=BACKLIST_CURSOR_KEY, next_offset=101, total=10_000)
    )
    uc = _use_case(probe, tasks, cursors)

    result = await uc.execute(chunk_size=1000, target_depth=100)

    assert result.seeded == 0
    assert result.next_offset == 101  # cursor not advanced
    assert tasks.seed_calls == []


async def test_reset_reprobes_even_with_existing_cursor() -> None:
    probe = _FakeProbe(highest=500)
    tasks = _FakeTaskRepo()
    cursors = _FakeCursorRepo(
        DiscoveryCursor(expression=BACKLIST_CURSOR_KEY, next_offset=300, total=500)
    )
    uc = _use_case(probe, tasks, cursors)

    result = await uc.execute(chunk_size=50, reset=True)

    assert probe.calls == 1
    assert result.range_low == 1  # restarted from the top


async def test_rejects_non_positive_chunk() -> None:
    uc = _use_case(_FakeProbe(highest=10), _FakeTaskRepo(), _FakeCursorRepo())
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        await uc.execute(chunk_size=0)
