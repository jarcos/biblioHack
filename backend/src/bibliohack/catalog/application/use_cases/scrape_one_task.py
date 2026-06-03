"""ScrapeOneTask — the unit of work for the scrape worker.

One call performs the full pop-fetch-parse-persist-transition cycle for
exactly one TITN:

    1. Claim a `discovered` task via ScrapeTaskRepository (SKIP LOCKED).
    2. Fetch its rendered HTML via OpacGateway.
    3. Branch on FetchOutcome:
        - OK         → parse → CatalogIngestRepository.persist → mark_parsed.
        - NOT_FOUND  → mark_not_found.
        - PERMANENT  → mark_failed (no retry).
        - TRANSIENT  → mark_failed with exponential-backoff next_retry_at.

Everything happens inside the caller's transaction, so partial writes
roll back together. The worker (next commit) wraps this in a loop with
graceful shutdown.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from bibliohack.catalog.application.ports import (
    FetchOutcome,
    OpacUnavailableError,
    ScrapeTask,
    TaskState,
)
from bibliohack.catalog.domain.media_filter import (
    MediaTypeFilter,
    MediaTypeFilterPreset,
)
from bibliohack.catalog.infrastructure.absysnet.parser import (
    ParseError,
    parse_record_html,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bibliohack.catalog.application.ports import (
        CatalogIngestRepository,
        OpacGateway,
        ScrapeTaskRepository,
    )

log = logging.getLogger(__name__)


class ScrapeStepOutcome(StrEnum):
    """What `ScrapeOneTask` produced for a single task."""

    PERSISTED = "persisted"
    NOT_FOUND = "not_found"
    PERMANENT_ERROR = "permanent_error"
    TRANSIENT_ERROR = "transient_error"
    SKIPPED_NON_BOOK = "skipped_non_book"
    NO_WORK = "no_work"  # claim returned an empty batch


@dataclass(frozen=True, slots=True)
class ScrapeStepResult:
    """Summary of one ScrapeOneTask invocation."""

    outcome: ScrapeStepOutcome
    titn: int | None = None
    error: str | None = None


# Backoff schedule for transient failures — capped so we don't park a TITN
# for a week. attempts 1..5 → 30s, 1m, 4m, 16m, 64m. Beyond that, the row
# stays at FAILED indefinitely (operator can re-set status to discovered
# if they want to retry).
_BACKOFF_SECONDS = (30, 60, 240, 960, 3840)


class ScrapeOneTask:
    """Single-step worker: claim → fetch → parse → persist → transition."""

    def __init__(
        self,
        *,
        task_repository: ScrapeTaskRepository,
        ingest_repository: CatalogIngestRepository,
        gateway: OpacGateway,
        media_filter: MediaTypeFilter | None = None,
        claim_states: Sequence[TaskState] = (TaskState.DISCOVERED,),
        require_refresh_due: bool = False,
    ) -> None:
        self._tasks = task_repository
        self._ingest = ingest_repository
        self._gateway = gateway
        # Default: books only (printed + electronic monographs).
        self._media_filter = media_filter or MediaTypeFilter.from_preset(MediaTypeFilterPreset.BOOK)
        # Initial crawl claims `discovered`; the refresh worker passes
        # claim_states=(PARSED,) + require_refresh_due=True to re-scrape
        # records whose availability is due for a fresh snapshot.
        self._claim_states = claim_states
        self._require_refresh_due = require_refresh_due

    async def execute(self) -> ScrapeStepResult:
        # 1. Claim one task atomically.
        batch = await self._tasks.claim_next_batch(
            limit=1,
            states=self._claim_states,
            require_refresh_due=self._require_refresh_due,
        )
        if not batch:
            return ScrapeStepResult(outcome=ScrapeStepOutcome.NO_WORK)
        task = batch[0]

        # 2. Fetch.
        try:
            fetch = await self._gateway.fetch_record(task.titn)
        except OpacUnavailableError as exc:
            return await self._handle_transient(task, error=str(exc))

        # 3. Branch on outcome.
        if fetch.outcome is FetchOutcome.NOT_FOUND:
            await self._tasks.mark_not_found(task.titn)
            return ScrapeStepResult(outcome=ScrapeStepOutcome.NOT_FOUND, titn=int(task.titn))

        if fetch.outcome is FetchOutcome.PERMANENT_ERROR:
            await self._tasks.mark_failed(
                task.titn,
                error=fetch.error or "permanent_error",
                next_retry_at=None,
            )
            return ScrapeStepResult(
                outcome=ScrapeStepOutcome.PERMANENT_ERROR,
                titn=int(task.titn),
                error=fetch.error,
            )

        if fetch.outcome is FetchOutcome.TRANSIENT_ERROR:
            return await self._handle_transient(task, error=fetch.error or "transient_error")

        # OK — parse and persist.
        if not fetch.html:
            return await self._handle_transient(task, error="OPAC returned 200 with no HTML body")

        try:
            parsed = parse_record_html(fetch.html, expected_titn=task.titn)
        except ParseError as exc:
            # Parser failure isn't transient — the HTML simply isn't what we
            # expect. Mark permanent so we don't retry indefinitely.
            await self._tasks.mark_failed(
                task.titn, error=f"parse error: {exc}", next_retry_at=None
            )
            return ScrapeStepResult(
                outcome=ScrapeStepOutcome.PERMANENT_ERROR,
                titn=int(task.titn),
                error=str(exc),
            )

        # Media-type filter: skip records that don't match (magazines, CDs,
        # audiobooks if not opted in, etc.). The task is marked skipped so we
        # don't fetch it again, but no record is written.
        if not self._media_filter.accepts(
            parsed.record.record_type, parsed.record.bibliographic_level
        ):
            await self._tasks.mark_skipped_non_book(task.titn)
            log.info(
                "scrape.skipped_non_book titn=%d ld06=%s ld07=%s doc_type=%s",
                int(task.titn),
                parsed.record.record_type,
                parsed.record.bibliographic_level,
                parsed.record.document_type,
            )
            return ScrapeStepResult(outcome=ScrapeStepOutcome.SKIPPED_NON_BOOK, titn=int(task.titn))

        source_hash = hashlib.sha256(fetch.html.encode("utf-8")).digest()
        ingest = await self._ingest.persist_parsed_record(
            parsed=parsed.record,
            copies=list(parsed.copies),
            source_url=fetch.final_url,
            source_hash=source_hash,
        )
        await self._tasks.mark_parsed(task.titn, source_hash=source_hash)

        log.info(
            "scrape.persisted titn=%d record_id=%s was_new=%s copies=%d snapshots=%d",
            int(task.titn),
            ingest.record_id,
            ingest.was_new,
            ingest.copies_persisted,
            ingest.snapshots_persisted,
        )

        return ScrapeStepResult(outcome=ScrapeStepOutcome.PERSISTED, titn=int(task.titn))

    async def _handle_transient(self, task: ScrapeTask, *, error: str) -> ScrapeStepResult:
        attempts = task.attempt_count + 1
        # Use the (attempts-1)th entry of the schedule; clamp at the tail.
        seconds = _BACKOFF_SECONDS[min(attempts, len(_BACKOFF_SECONDS)) - 1]
        next_retry = datetime.now(tz=UTC) + timedelta(seconds=seconds)
        await self._tasks.mark_failed(task.titn, error=error, next_retry_at=next_retry)
        return ScrapeStepResult(
            outcome=ScrapeStepOutcome.TRANSIENT_ERROR,
            titn=int(task.titn),
            error=error,
        )
