"""The shared publication-year plausibility ceiling."""

from __future__ import annotations

from datetime import UTC, datetime

from bibliohack.catalog.domain.pub_year import (
    PUB_YEAR_FUTURE_BUFFER,
    max_plausible_pub_year,
)


def test_ceiling_is_injected_year_plus_buffer() -> None:
    now = datetime(2026, 6, 20, tzinfo=UTC)
    assert max_plausible_pub_year(now) == 2026 + PUB_YEAR_FUTURE_BUFFER


def test_ceiling_defaults_to_current_year_plus_buffer() -> None:
    expected = datetime.now(UTC).year + PUB_YEAR_FUTURE_BUFFER
    assert max_plausible_pub_year() == expected


def test_buffer_tolerates_next_year_but_not_beyond() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    ceiling = max_plausible_pub_year(now)
    assert ceiling == 2027  # next-year forthcoming imprint is allowed
    assert ceiling < 2028  # but the year after is not
