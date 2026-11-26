"""Crawler health as Prometheus text: what the alerts read, and the cache it doubles as."""

from __future__ import annotations

from datetime import UTC, datetime

from bibliohack.ops.domain.health import (
    CrawlerHealth,
    CursorProgress,
    RecordCounts,
    parse_record_counts,
    render_textfile,
)

_NOW = datetime(2026, 11, 26, 22, 0, tzinfo=UTC)


def _health(**overrides: object) -> CrawlerHealth:
    fields: dict[str, object] = {
        "collected_at": _NOW,
        "expected_schema_revision": "20260930_0024",
        "database_schema_revision": "20260930_0024",
        "last_availability_snapshot_at": datetime(2026, 11, 26, 21, 11, 1, tzinfo=UTC),
        "last_relevance_update_at": datetime(2026, 11, 26, 11, 41, 37, tzinfo=UTC),
        "scrape_failures_last_hour": 3,
        "cursors": (
            CursorProgress(expression="(@fepu>=2024)", next_offset=67_909, total=67_909),
            CursorProgress(expression="__backlist_titn__", next_offset=2_686_840, total=2_686_839),
        ),
        "record_counts": RecordCounts(
            total=1_707_091, embedded=196_441, counted_at=datetime(2026, 11, 26, 21, 0, tzinfo=UTC)
        ),
    }
    fields.update(overrides)
    return CrawlerHealth(**fields)  # type: ignore[arg-type]


def _samples(text: str) -> dict[str, str]:
    """Metric line (name + labels) → value, ignoring HELP/TYPE comments."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            key, value = line.rsplit(" ", 1)
            out[key] = value
    return out


def test_schema_drift_is_any_difference_from_the_expected_revision() -> None:
    assert not _health().schema_drift
    assert _health(database_schema_revision="20260716_0023").schema_drift
    assert _health(database_schema_revision="20261201_0025").schema_drift
    assert _health(database_schema_revision=None).schema_drift


def test_renders_every_signal_the_alerts_read() -> None:
    samples = _samples(render_textfile(_health()))

    assert samples["bibliohack_health_last_run_timestamp_seconds"] == str(int(_NOW.timestamp()))
    assert samples["bibliohack_schema_drift"] == "0"
    assert (
        samples['bibliohack_schema_revision_info{database="20260930_0024",image="20260930_0024"}']
        == "1"
    )
    assert samples["bibliohack_availability_last_snapshot_timestamp_seconds"] == str(
        int(datetime(2026, 11, 26, 21, 11, 1, tzinfo=UTC).timestamp())
    )
    assert samples["bibliohack_relevance_last_update_timestamp_seconds"] == str(
        int(datetime(2026, 11, 26, 11, 41, 37, tzinfo=UTC).timestamp())
    )
    assert samples["bibliohack_scrape_failures_last_hour"] == "3"
    assert samples['bibliohack_discovery_cursor_next_offset{expression="(@fepu>=2024)"}'] == "67909"
    assert samples['bibliohack_discovery_cursor_total{expression="__backlist_titn__"}'] == "2686839"
    assert samples["bibliohack_records_total"] == "1707091"
    assert samples["bibliohack_records_embedded"] == "196441"
    assert samples["bibliohack_records_counted_timestamp_seconds"] == str(
        int(datetime(2026, 11, 26, 21, 0, tzinfo=UTC).timestamp())
    )


def test_every_metric_carries_help_and_type() -> None:
    text = render_textfile(_health())
    names = {
        line.split("{")[0].split(" ")[0] for line in text.splitlines() if line[:1] not in ("", "#")
    }

    for name in names:
        assert f"# HELP {name} " in text
        assert f"# TYPE {name} gauge" in text
    assert text.endswith("\n")


def test_drift_renders_as_one_with_both_revisions() -> None:
    samples = _samples(render_textfile(_health(database_schema_revision=None)))

    assert samples["bibliohack_schema_drift"] == "1"
    assert samples['bibliohack_schema_revision_info{database="",image="20260930_0024"}'] == "1"


def test_unknown_timestamps_render_as_zero_so_they_read_as_stale() -> None:
    # Never seen (or unreadable) is as bad as very old: the staleness alerts
    # compare against time(), so 0 fires them instead of hiding the gap.
    samples = _samples(
        render_textfile(_health(last_availability_snapshot_at=None, last_relevance_update_at=None))
    )

    assert samples["bibliohack_availability_last_snapshot_timestamp_seconds"] == "0"
    assert samples["bibliohack_relevance_last_update_timestamp_seconds"] == "0"


def test_unknown_counts_are_left_out_rather_than_invented() -> None:
    samples = _samples(
        render_textfile(
            _health(
                scrape_failures_last_hour=None,
                record_counts=None,
                cursors=(CursorProgress(expression="x", next_offset=5, total=None),),
            )
        )
    )

    assert "bibliohack_scrape_failures_last_hour" not in samples
    assert "bibliohack_records_total" not in samples
    assert "bibliohack_records_embedded" not in samples
    assert samples['bibliohack_discovery_cursor_next_offset{expression="x"}'] == "5"
    assert 'bibliohack_discovery_cursor_total{expression="x"}' not in samples


def test_label_values_are_escaped() -> None:
    text = render_textfile(
        _health(cursors=(CursorProgress(expression='a"b\\c\nd', next_offset=1, total=2),))
    )

    assert 'bibliohack_discovery_cursor_total{expression="a\\"b\\\\c\\nd"} 2' in text


def test_counts_round_trip_through_the_textfile() -> None:
    counts = RecordCounts(
        total=1_707_091, embedded=196_441, counted_at=datetime(2026, 11, 26, 21, 0, tzinfo=UTC)
    )

    assert parse_record_counts(render_textfile(_health(record_counts=counts))) == counts


def test_parsing_needs_all_three_count_lines() -> None:
    text = render_textfile(_health(record_counts=None))

    assert parse_record_counts(text) is None
    assert parse_record_counts("") is None
    assert (
        parse_record_counts("bibliohack_records_total 5\nbibliohack_records_embedded 2\n") is None
    )
