"""PublishHealthMetrics: gather the crawler's health facts and write them for Prometheus."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from bibliohack.ops.application.use_cases.publish_health_metrics import (
    RECOUNT_INTERVAL,
    PublishHealthMetrics,
)
from bibliohack.ops.domain.health import (
    CrawlerHealth,
    CursorProgress,
    RecordCounts,
    render_textfile,
)

if TYPE_CHECKING:
    from bibliohack.ops.application.ports import HealthReader, MetricsFile

_NOW = datetime(2026, 11, 26, 22, 0, tzinfo=UTC)
_SNAPSHOT = datetime(2026, 11, 26, 21, 11, tzinfo=UTC)
_RELEVANCE = datetime(2026, 11, 26, 11, 41, tzinfo=UTC)


class _FakeReader:
    def __init__(self) -> None:
        self.count_calls = 0
        self.failures_since: list[datetime] = []

    async def schema_revision(self) -> str | None:
        return "20260930_0024"

    async def last_availability_snapshot_at(self) -> datetime | None:
        return _SNAPSHOT

    async def last_relevance_update_at(self) -> datetime | None:
        return _RELEVANCE

    async def scrape_failures_since(self, since: datetime) -> int | None:
        self.failures_since.append(since)
        return 4

    async def discovery_cursors(self) -> list[CursorProgress]:
        return [CursorProgress(expression="(@fepu>=2024)", next_offset=10, total=10)]

    async def record_counts(self) -> tuple[int, int] | None:
        self.count_calls += 1
        return (1_707_091, 196_441)


class _FakeFile:
    def __init__(self, content: str | None = None) -> None:
        self.content = content
        self.writes = 0

    def read(self) -> str | None:
        return self.content

    def write(self, content: str) -> None:
        self.content = content
        self.writes += 1


def _use_case(reader: _FakeReader, metrics_file: _FakeFile) -> PublishHealthMetrics:
    return PublishHealthMetrics(
        reader=cast("HealthReader", reader),
        metrics_file=cast("MetricsFile", metrics_file),
        expected_schema_revision="20260930_0024",
        clock=lambda: _NOW,
    )


async def test_first_run_counts_records_and_writes_every_fact() -> None:
    reader, metrics_file = _FakeReader(), _FakeFile()

    health = await _use_case(reader, metrics_file).execute()

    assert reader.count_calls == 1
    assert health.collected_at == _NOW
    assert not health.schema_drift
    assert health.last_availability_snapshot_at == _SNAPSHOT
    assert health.last_relevance_update_at == _RELEVANCE
    assert health.scrape_failures_last_hour == 4
    assert reader.failures_since == [_NOW - timedelta(hours=1)]
    assert health.cursors == (CursorProgress(expression="(@fepu>=2024)", next_offset=10, total=10),)
    assert health.record_counts == RecordCounts(total=1_707_091, embedded=196_441, counted_at=_NOW)
    assert metrics_file.writes == 1
    assert metrics_file.content == render_textfile(health)


async def test_recent_counts_are_reused_instead_of_rescanning() -> None:
    # Counting embeddings is a ~27 s scan of the record table on the NAS; the
    # previous textfile is the cache.
    earlier = _NOW - RECOUNT_INTERVAL + timedelta(minutes=10)
    cached = RecordCounts(total=1_700_000, embedded=190_000, counted_at=earlier)
    previous = await _use_case(_FakeReader(), _FakeFile()).execute()
    reader = _FakeReader()
    metrics_file = _FakeFile(render_textfile(_with_counts(previous, cached)))

    health = await _use_case(reader, metrics_file).execute()

    assert reader.count_calls == 0
    assert health.record_counts == cached


async def test_counts_older_than_the_interval_are_recounted() -> None:
    stale = RecordCounts(total=1, embedded=1, counted_at=_NOW - RECOUNT_INTERVAL)
    previous = await _use_case(_FakeReader(), _FakeFile()).execute()
    reader = _FakeReader()
    metrics_file = _FakeFile(render_textfile(_with_counts(previous, stale)))

    health = await _use_case(reader, metrics_file).execute()

    assert reader.count_calls == 1
    assert health.record_counts == RecordCounts(total=1_707_091, embedded=196_441, counted_at=_NOW)


async def test_unreadable_counts_are_left_out() -> None:
    class _NoCounts(_FakeReader):
        async def record_counts(self) -> tuple[int, int] | None:
            return None

    health = await _use_case(_NoCounts(), _FakeFile()).execute()

    assert health.record_counts is None


async def test_a_drifted_database_is_reported_not_hidden() -> None:
    class _Drifted(_FakeReader):
        async def schema_revision(self) -> str | None:
            return "20261201_0025"

    metrics_file = _FakeFile()
    health = await _use_case(_Drifted(), metrics_file).execute()

    assert health.schema_drift
    assert "bibliohack_schema_drift 1" in (metrics_file.content or "")


def _with_counts(health: CrawlerHealth, counts: RecordCounts) -> CrawlerHealth:
    return replace(health, record_counts=counts)


async def test_without_a_clock_it_stamps_the_current_time() -> None:
    before = datetime.now(tz=UTC)
    health = await PublishHealthMetrics(
        reader=cast("HealthReader", _FakeReader()),
        metrics_file=cast("MetricsFile", _FakeFile()),
        expected_schema_revision="20260930_0024",
    ).execute()

    assert before <= health.collected_at <= datetime.now(tz=UTC)
