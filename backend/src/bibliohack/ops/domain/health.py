"""Crawler-plane health, as facts and as Prometheus text. Pure: no I/O.

From 2026-09-30 to 2026-11-26 the crawler failed every record write for 57
days and nothing said so: the jobs exited 0, discovery kept moving its
cursors, and the only symptoms were in the data. So these signals are
data-level (when did the last availability snapshot land, is the database
on the revision this image expects, how many tasks failed in the last hour),
not "did the job exit 0". Prometheus reads them through node-exporter's
textfile collector and alerts on them
(`infra/monitoring/prometheus/bibliohack-alerts.yml`).

The textfile is also the cache for the one expensive fact, the record and
embedding counts (a ~27 s scan of the record table on the NAS):
`parse_record_counts` reads them back so the job only recounts every few
hours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class CursorProgress:
    """How far one discovery expression has paged through its result set."""

    expression: str
    next_offset: int
    total: int | None


@dataclass(frozen=True, slots=True)
class RecordCounts:
    """Mirror size and embedding coverage, as of `counted_at`."""

    total: int
    embedded: int
    counted_at: datetime


@dataclass(frozen=True, slots=True)
class CrawlerHealth:
    """One reading of the crawler plane's health. `None` means unknown."""

    collected_at: datetime
    expected_schema_revision: str
    database_schema_revision: str | None
    last_availability_snapshot_at: datetime | None
    last_relevance_update_at: datetime | None
    scrape_failures_last_hour: int | None
    cursors: tuple[CursorProgress, ...]
    record_counts: RecordCounts | None

    @property
    def schema_drift(self) -> bool:
        """Ahead or behind, a different revision means image and database disagree."""
        return self.database_schema_revision != self.expected_schema_revision


_TOTAL = "bibliohack_records_total"
_EMBEDDED = "bibliohack_records_embedded"
_COUNTED_AT = "bibliohack_records_counted_timestamp_seconds"


def render_textfile(health: CrawlerHealth) -> str:
    """The Prometheus text exposition of `health` (all gauges)."""
    out = _Exposition()
    out.gauge(
        "bibliohack_health_last_run_timestamp_seconds",
        "When the crawler last wrote these metrics.",
        [({}, _ts(health.collected_at))],
    )
    out.gauge(
        "bibliohack_schema_drift",
        "1 when the database is on a different Alembic revision than this crawler image expects.",
        [({}, int(health.schema_drift))],
    )
    out.gauge(
        "bibliohack_schema_revision_info",
        "Alembic revision of the database and the one this crawler image expects.",
        [
            (
                {
                    "database": health.database_schema_revision or "",
                    "image": health.expected_schema_revision,
                },
                1,
            )
        ],
    )
    out.gauge(
        "bibliohack_availability_last_snapshot_timestamp_seconds",
        "Newest availability snapshot (0 = none or unreadable).",
        [({}, _ts(health.last_availability_snapshot_at))],
    )
    out.gauge(
        "bibliohack_relevance_last_update_timestamp_seconds",
        "Last relevance recompute (0 = never or unreadable).",
        [({}, _ts(health.last_relevance_update_at))],
    )
    if health.scrape_failures_last_hour is not None:
        out.gauge(
            "bibliohack_scrape_failures_last_hour",
            "Scrape tasks that ended failed in the last hour.",
            [({}, health.scrape_failures_last_hour)],
        )
    out.gauge(
        "bibliohack_discovery_cursor_next_offset",
        "Next result offset each discovery expression will fetch.",
        [({"expression": c.expression}, c.next_offset) for c in health.cursors],
    )
    out.gauge(
        "bibliohack_discovery_cursor_total",
        "Result-set size each discovery expression last saw.",
        [({"expression": c.expression}, c.total) for c in health.cursors if c.total is not None],
    )
    counts = health.record_counts
    if counts is not None:
        out.gauge(_TOTAL, "Records in the mirror.", [({}, counts.total)])
        out.gauge(_EMBEDDED, "Records with an embedding.", [({}, counts.embedded)])
        out.gauge(_COUNTED_AT, "When the record counts were taken.", [({}, _ts(counts.counted_at))])
    return out.text()


_COUNT_LINE = re.compile(r"^(" + "|".join((_TOTAL, _EMBEDDED, _COUNTED_AT)) + r") (\d+)$", re.M)


def parse_record_counts(text: str) -> RecordCounts | None:
    """Read back the counts a previous `render_textfile` wrote, if all are there."""
    values = {name: int(value) for name, value in _COUNT_LINE.findall(text)}
    if len(values) != 3:
        return None
    return RecordCounts(
        total=values[_TOTAL],
        embedded=values[_EMBEDDED],
        counted_at=datetime.fromtimestamp(values[_COUNTED_AT], tz=UTC),
    )


def _ts(value: datetime | None) -> int:
    # Unknown reads as the epoch: every staleness alert compares with time(),
    # so a gap fires them instead of hiding.
    return 0 if value is None else int(value.timestamp())


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _Exposition:
    def __init__(self) -> None:
        self._lines: list[str] = []

    def gauge(self, name: str, help_text: str, samples: list[tuple[dict[str, str], int]]) -> None:
        self._lines.append(f"# HELP {name} {help_text}")
        self._lines.append(f"# TYPE {name} gauge")
        for labels, value in samples:
            rendered = ",".join(f'{key}="{_escape(val)}"' for key, val in labels.items())
            self._lines.append(f"{name}{{{rendered}}} {value}" if rendered else f"{name} {value}")

    def text(self) -> str:
        return "\n".join(self._lines) + "\n"
