"""RunScrapeWorker — loop driver for ScrapeOneTask.

Repeatedly executes one `ScrapeOneTask` until either:
- `NO_WORK` is returned consecutively `idle_giveup` times (queue is empty
  for now — caller can re-run later), or
- `max_tasks` has been reached, or
- the externally-set `stop` event fires (Ctrl+C / SIGTERM).

The session lifecycle is the caller's concern — each step rides one
transaction provided by the calling layer. That keeps the loop trivial
and lets the CLI choose between "one transaction per step" (the safe
default — partial work commits as it succeeds) and "one big transaction"
(useful for testing).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bibliohack.catalog.application.use_cases.scrape_one_task import (
    ScrapeOneTask,
    ScrapeStepOutcome,
    ScrapeStepResult,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

log = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkerStats:
    """Running tally for one worker session."""

    persisted: int = 0
    not_found: int = 0
    permanent_errors: int = 0
    transient_errors: int = 0
    skipped_non_book: int = 0
    no_work_hits: int = 0
    # Iterations where an exception escaped the step entirely (should be ~0 now
    # that ScrapeOneTask isolates DB errors; tracked as a safety-net signal).
    unexpected_errors: int = 0

    @property
    def total(self) -> int:
        return (
            self.persisted
            + self.not_found
            + self.permanent_errors
            + self.transient_errors
            + self.skipped_non_book
            + self.unexpected_errors
        )

    def record(self, result: ScrapeStepResult) -> None:
        match result.outcome:
            case ScrapeStepOutcome.PERSISTED:
                self.persisted += 1
            case ScrapeStepOutcome.NOT_FOUND:
                self.not_found += 1
            case ScrapeStepOutcome.PERMANENT_ERROR:
                self.permanent_errors += 1
            case ScrapeStepOutcome.TRANSIENT_ERROR:
                self.transient_errors += 1
            case ScrapeStepOutcome.SKIPPED_NON_BOOK:
                self.skipped_non_book += 1
            case ScrapeStepOutcome.NO_WORK:
                self.no_work_hits += 1


@dataclass(slots=True)
class WorkerControl:
    """Externally-settable signal for graceful shutdown."""

    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    def request_stop(self) -> None:
        self._stop.set()

    def should_stop(self) -> bool:
        return self._stop.is_set()


class RunScrapeWorker:
    """Long-running loop over `ScrapeOneTask`.

    The `step_factory` callable is what isolates the session boundary —
    each call yields a freshly-built `ScrapeOneTask` (with its own
    repository + ingest impls wired to a fresh session). The CLI passes a
    factory that opens a transaction per step; tests pass one that reuses
    a single in-memory session.
    """

    def __init__(
        self,
        *,
        step_factory: Callable[[], AsyncIterator[ScrapeOneTask]],
        control: WorkerControl | None = None,
        max_tasks: int | None = None,
        idle_giveup: int = 5,
        idle_sleep_seconds: float = 1.0,
    ) -> None:
        self._step_factory = step_factory
        self._control = control or WorkerControl()
        self._max_tasks = max_tasks
        self._idle_giveup = idle_giveup
        self._idle_sleep_seconds = idle_sleep_seconds

    @property
    def control(self) -> WorkerControl:
        return self._control

    async def execute(
        self,
        *,
        on_step: Callable[[ScrapeStepResult], Awaitable[None] | None] | None = None,
    ) -> WorkerStats:
        stats = WorkerStats()
        consecutive_idle = 0

        while not self._control.should_stop():
            if self._max_tasks is not None and stats.total >= self._max_tasks:
                log.info("worker.max_tasks_reached n=%d", stats.total)
                break

            # Each iteration gets a fresh ScrapeOneTask (and underneath, a
            # fresh session). The factory is an async context manager that
            # commits on clean exit, so each step's writes commit immediately.
            #
            # Defence in depth: ScrapeOneTask isolates its own DB errors, but
            # if anything unexpected still escapes a step, log it and keep the
            # loop alive rather than aborting the whole run. The step's
            # transaction is rolled back by its context manager on the way out.
            try:
                async for step in self._step_factory():
                    result = await step.execute()
                    stats.record(result)
                    if on_step is not None:
                        maybe_awaitable = on_step(result)
                        if maybe_awaitable is not None:
                            await maybe_awaitable

                    if result.outcome is ScrapeStepOutcome.NO_WORK:
                        consecutive_idle += 1
                    else:
                        consecutive_idle = 0
            except Exception:
                log.exception("worker.iteration_failed — continuing")
                stats.unexpected_errors += 1
                consecutive_idle = 0
                await asyncio.sleep(self._idle_sleep_seconds)

            if consecutive_idle >= self._idle_giveup:
                log.info(
                    "worker.idle_giveup consecutive=%d limit=%d",
                    consecutive_idle,
                    self._idle_giveup,
                )
                break

            if consecutive_idle > 0:
                await asyncio.sleep(self._idle_sleep_seconds)

        return stats
