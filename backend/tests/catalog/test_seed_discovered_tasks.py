"""Tests for the `SeedDiscoveredTasks` use case.

Drives the use case with a fake repository — we only need to verify the
orchestration (validation, what's passed to the repo, what comes back).
The repository's own behaviour against a real DB is covered by
`test_scrape_task_repository.py` (integration).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bibliohack.catalog.application.use_cases.seed_discovered_tasks import (
    SeedDiscoveredTasks,
)
from bibliohack.catalog.domain.titn import Titn

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import ScrapeTask, StateCounts


class FakeScrapeTaskRepository:
    """Minimal stand-in. We only exercise `seed_range`; everything else just
    has to satisfy the Protocol shape so callers can substitute this."""

    def __init__(self, *, will_insert: int) -> None:
        self.calls: list[tuple[int, int]] = []
        self._will_insert = will_insert

    async def seed_range(self, low: Titn, high: Titn) -> int:
        self.calls.append((int(low), int(high)))
        return self._will_insert

    # — unused stubs to satisfy the Protocol shape —
    async def seed_one(self, titn: Titn) -> bool:  # pragma: no cover
        return True

    async def claim_next_batch(self, **_kwargs: object) -> list[ScrapeTask]:  # pragma: no cover
        return []

    async def mark_parsed(self, titn: Titn, **_kwargs: object) -> None:  # pragma: no cover
        return None

    async def mark_not_found(self, titn: Titn) -> None:  # pragma: no cover
        return None

    async def mark_failed(self, titn: Titn, **_kwargs: object) -> None:  # pragma: no cover
        return None

    async def get(self, titn: Titn) -> ScrapeTask | None:  # pragma: no cover
        return None

    async def count_by_state(self) -> StateCounts:  # pragma: no cover
        from bibliohack.catalog.application.ports import StateCounts as _StateCounts

        return _StateCounts(counts={})


# ───────────────────────────────────────────────────────────────


async def test_executes_and_returns_seed_result() -> None:
    repo = FakeScrapeTaskRepository(will_insert=42)
    result = await SeedDiscoveredTasks(repo).execute(Titn(1), Titn(100))  # type: ignore[arg-type]

    assert result.inserted == 42
    assert result.range_low == 1
    assert result.range_high == 100
    assert result.range_size == 100
    assert result.already_known == 100 - 42
    assert repo.calls == [(1, 100)]


async def test_rejects_inverted_range() -> None:
    repo = FakeScrapeTaskRepository(will_insert=0)
    with pytest.raises(ValueError, match="must be <="):
        await SeedDiscoveredTasks(repo).execute(Titn(100), Titn(50))  # type: ignore[arg-type]


async def test_single_titn_range_works() -> None:
    repo = FakeScrapeTaskRepository(will_insert=1)
    result = await SeedDiscoveredTasks(repo).execute(Titn(7), Titn(7))  # type: ignore[arg-type]
    assert result.range_size == 1
    assert result.inserted == 1
    assert result.already_known == 0


async def test_already_known_when_no_new_rows_inserted() -> None:
    """Idempotent re-run case: range is 100 wide but 0 new rows."""
    repo = FakeScrapeTaskRepository(will_insert=0)
    result = await SeedDiscoveredTasks(repo).execute(Titn(1), Titn(100))  # type: ignore[arg-type]
    assert result.inserted == 0
    assert result.already_known == 100
