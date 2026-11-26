"""PublishHealthMetrics — read the crawler plane's health and write it for Prometheus.

Runs every 10 minutes from the crawler's crontab (`run-job.sh health`). Every
fact is cheap except the record/embedding count, which is recounted only
when the copy in the previous textfile is older than `RECOUNT_INTERVAL`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bibliohack.ops.domain.health import (
    CrawlerHealth,
    RecordCounts,
    parse_record_counts,
    render_textfile,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from bibliohack.ops.application.ports import HealthReader, MetricsFile

# The embedding backfill runs every 3 h and the stall alert looks back 6 h,
# so a 3 h-old count is fresh enough and costs one scan per backfill run.
RECOUNT_INTERVAL = timedelta(hours=3)
FAILURE_WINDOW = timedelta(hours=1)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class PublishHealthMetrics:
    def __init__(
        self,
        *,
        reader: HealthReader,
        metrics_file: MetricsFile,
        expected_schema_revision: str,
        clock: Callable[[], datetime] = _utcnow,
        recount_interval: timedelta = RECOUNT_INTERVAL,
    ) -> None:
        self._reader = reader
        self._file = metrics_file
        self._expected = expected_schema_revision
        self._clock = clock
        self._recount_interval = recount_interval

    async def execute(self) -> CrawlerHealth:
        now = self._clock()
        health = CrawlerHealth(
            collected_at=now,
            expected_schema_revision=self._expected,
            database_schema_revision=await self._reader.schema_revision(),
            last_availability_snapshot_at=await self._reader.last_availability_snapshot_at(),
            last_relevance_update_at=await self._reader.last_relevance_update_at(),
            scrape_failures_last_hour=await self._reader.scrape_failures_since(
                now - FAILURE_WINDOW
            ),
            cursors=tuple(await self._reader.discovery_cursors()),
            record_counts=self._cached_counts(now) or await self._count(now),
        )
        self._file.write(render_textfile(health))
        return health

    def _cached_counts(self, now: datetime) -> RecordCounts | None:
        previous = self._file.read()
        counts = parse_record_counts(previous) if previous else None
        if counts is None or now - counts.counted_at >= self._recount_interval:
            return None
        return counts

    async def _count(self, now: datetime) -> RecordCounts | None:
        counted = await self._reader.record_counts()
        if counted is None:
            return None
        total, embedded = counted
        return RecordCounts(total=total, embedded=embedded, counted_at=now)
