"""Unit test: a DB error during persist is isolated, not fatal.

When `persist_parsed_record` raises a database error (e.g. a value that
violates a column constraint), `ScrapeOneTask` must roll back just that record
(via the SAVEPOINT), mark the task `failed`, and return PERMANENT_ERROR — so
the worker loop keeps going instead of the whole run aborting. Regression test
for the StringDataRightTruncation crash that froze catalogue growth.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy.exc import IntegrityError

from bibliohack.catalog.application.ports import FetchOutcome, FetchResult, ScrapeTask, TaskState
from bibliohack.catalog.application.use_cases.scrape_one_task import (
    ScrapeOneTask,
    ScrapeStepOutcome,
)
from bibliohack.catalog.domain.titn import Titn

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from bibliohack.catalog.application.ports import (
        CatalogIngestRepository,
        OpacGateway,
        ScrapeTaskRepository,
    )

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeSession:
    """Just enough of AsyncSession for `_savepoint`: a no-op nested context."""

    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        yield


class _OneTaskRepo:
    """Hands out one DISCOVERED task, then records the transition calls."""

    def __init__(self, titn: int) -> None:
        self._titn = titn
        self._handed_out = False
        self.failed: list[tuple[int, str | None]] = []
        self.parsed: list[int] = []

    async def claim_next_batch(
        self,
        *,
        limit: int = 1,
        states: Sequence[TaskState] = (TaskState.DISCOVERED,),
        require_refresh_due: bool = False,
    ) -> list[ScrapeTask]:
        if self._handed_out:
            return []
        self._handed_out = True
        return [ScrapeTask(titn=Titn(self._titn), status=TaskState.DISCOVERED)]

    async def mark_failed(self, titn: Titn, *, error: str, next_retry_at: object) -> None:
        self.failed.append((int(titn), error))

    async def mark_parsed(self, titn: Titn, *, source_hash: bytes) -> None:
        self.parsed.append(int(titn))


class _BoomIngest:
    """persist_parsed_record always raises a DB error."""

    async def persist_parsed_record(self, **_kwargs: object) -> object:
        stmt = "INSERT INTO bibliographic_records …"
        orig = Exception("value too long for type character varying(64)")
        raise IntegrityError(stmt, {}, orig)


class _OkGateway:
    def __init__(self, html: str) -> None:
        self._html = html

    async def fetch_record(self, titn: Titn) -> FetchResult:
        return FetchResult(
            titn=titn,
            outcome=FetchOutcome.OK,
            url=f"https://test/?TITN={int(titn)}",
            final_url=f"https://test/?TITN={int(titn)}",
            status_code=200,
            html=self._html,
            latency_ms=1,
            bytes_in=len(self._html),
        )


async def test_persist_db_error_marks_failed_and_does_not_raise() -> None:
    html = (FIXTURES / "titn_1.html").read_text(encoding="utf-8")
    tasks = _OneTaskRepo(titn=1)
    step = ScrapeOneTask(
        task_repository=cast("ScrapeTaskRepository", tasks),
        ingest_repository=cast("CatalogIngestRepository", _BoomIngest()),
        gateway=cast("OpacGateway", _OkGateway(html)),
        session=cast("AsyncSession", _FakeSession()),
    )

    result = await step.execute()  # must NOT raise

    assert result.outcome is ScrapeStepOutcome.PERMANENT_ERROR
    assert result.titn == 1
    assert tasks.failed == [(1, "persist error: IntegrityError")]
    assert tasks.parsed == []  # never marked parsed
