"""RequeueFailedTasks — put `failed` scrape tasks back in the worker's queue."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from bibliohack.catalog.application.ports import FailedErrorCount
from bibliohack.catalog.application.use_cases.requeue_failed_tasks import (
    DEFAULT_MAX_ATTEMPTS,
    RequeueFailedTasks,
)

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import FailedTaskQueue


class _FakeQueue:
    def __init__(self, counts: list[FailedErrorCount], requeues: int = 0) -> None:
        self._counts = counts
        self._requeues = requeues
        self.requeue_calls: list[tuple[str | None, int, int | None]] = []

    async def failed_error_counts(self, *, prefix_length: int) -> list[FailedErrorCount]:
        self.prefix_length = prefix_length
        return self._counts

    async def requeue_failed(
        self, *, error_prefix: str | None, max_attempts: int, limit: int | None = None
    ) -> int:
        self.requeue_calls.append((error_prefix, max_attempts, limit))
        return self._requeues


def _use_case(queue: _FakeQueue) -> RequeueFailedTasks:
    return RequeueFailedTasks(queue=cast("FailedTaskQueue", queue))


_COUNTS = [
    FailedErrorCount(error_prefix="persist error: ProgrammingError", count=72_816),
    FailedErrorCount(error_prefix="parse error: No TITN field", count=764),
]


async def test_dry_run_reports_the_failures_and_changes_nothing() -> None:
    queue = _FakeQueue(_COUNTS, requeues=99)

    outcome = await _use_case(queue).execute(error_prefix="persist error", dry_run=True)

    assert outcome.requeued == 0
    assert outcome.failures_by_error == tuple(_COUNTS)
    assert queue.requeue_calls == []


async def test_run_requeues_with_the_given_filters() -> None:
    queue = _FakeQueue(_COUNTS, requeues=72_816)

    outcome = await _use_case(queue).execute(
        error_prefix="persist error", max_attempts=3, limit=500
    )

    assert outcome.requeued == 72_816
    assert outcome.failures_by_error == tuple(_COUNTS)
    assert queue.requeue_calls == [("persist error", 3, 500)]


async def test_defaults_cap_attempts_and_take_every_error() -> None:
    queue = _FakeQueue([])

    await _use_case(queue).execute()

    assert queue.requeue_calls == [(None, DEFAULT_MAX_ATTEMPTS, None)]


async def test_a_blank_prefix_means_every_error() -> None:
    queue = _FakeQueue([])

    await _use_case(queue).execute(error_prefix="   ")

    assert queue.requeue_calls == [(None, DEFAULT_MAX_ATTEMPTS, None)]


async def test_rejects_a_zero_attempt_cap() -> None:
    queue = _FakeQueue([])

    with pytest.raises(ValueError, match="max_attempts"):
        await _use_case(queue).execute(max_attempts=0)

    assert queue.requeue_calls == []


async def test_rejects_a_zero_limit() -> None:
    queue = _FakeQueue([])

    with pytest.raises(ValueError, match="limit"):
        await _use_case(queue).execute(limit=0)

    assert queue.requeue_calls == []
