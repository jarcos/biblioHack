"""RequeueFailedTasks — give `failed` scrape tasks another go.

The worker claims only `discovered` tasks, so a failure is final unless
something moves it back. Most failures are final for a reason (a page that
isn't a record), but some come from a cause that has since been fixed: from
2026-09-30 to 2026-11-26 every persist failed because the crawler image
predated migration 0024, which left 72,816 tasks failed with
"persist error: ProgrammingError". This puts them back without hand-written
SQL against production.

Bounded by an attempt cap so a record that fails every time can't loop, and
filterable by the leading text of the error so a run only touches the failures
whose cause is gone. A dry run reports what is failed and changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import FailedErrorCount, FailedTaskQueue

DEFAULT_MAX_ATTEMPTS = 5
ERROR_PREFIX_LENGTH = 40


@dataclass(frozen=True, slots=True)
class RequeueOutcome:
    """What was failed before the run, and how many tasks it requeued."""

    failures_by_error: tuple[FailedErrorCount, ...]
    requeued: int


class RequeueFailedTasks:
    """Move matching `failed` tasks back to `discovered`."""

    def __init__(self, *, queue: FailedTaskQueue) -> None:
        self._queue = queue

    async def execute(
        self,
        *,
        error_prefix: str | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> RequeueOutcome:
        if max_attempts < 1:
            msg = "max_attempts must be at least 1"
            raise ValueError(msg)
        if limit is not None and limit < 1:
            msg = "limit must be at least 1"
            raise ValueError(msg)
        # A blank prefix means every error; a real one is matched as given.
        prefix = error_prefix if error_prefix and error_prefix.strip() else None

        failures = tuple(await self._queue.failed_error_counts(prefix_length=ERROR_PREFIX_LENGTH))
        if dry_run:
            return RequeueOutcome(failures_by_error=failures, requeued=0)

        requeued = await self._queue.requeue_failed(
            error_prefix=prefix, max_attempts=max_attempts, limit=limit
        )
        return RequeueOutcome(failures_by_error=failures, requeued=requeued)
