"""Single source of truth for the plausible publication-year upper bound.

``pub_year`` comes from noisy upstream MARC data — "unknown date" sentinels
(9999, 0000), typos, and stray 4-digit runs the imprint parser may pick up. The
upper bound of what may be *stored* or *scored* as a real year is **dynamic**:
the current year plus a one-year buffer (libraries catalogue forthcoming titles
slightly ahead of publication), NOT a fixed far-future constant. So a source
typo like 2033 is rejected while a genuine next-year imprint survives — and,
because ``/browse`` sorts by ``pub_year`` desc, bogus future years can't float
to the top of the catalogue.

Centralised here so the parser, canon seed, relevance scoring, and the record
entity all enforce the same ceiling. The lower bound differs by context (the
record entity uses 1400 for pre-modern facsimiles; the parser/seed are looser),
so each caller keeps its own minimum and shares only this maximum.
"""

from __future__ import annotations

from datetime import UTC, datetime

# Tolerate next-year imprints so genuinely forthcoming titles aren't dropped.
PUB_YEAR_FUTURE_BUFFER = 1


def max_plausible_pub_year(now: datetime | None = None) -> int:
    """Largest year that may be stored/scored as a real publication year.

    ``now`` is injectable so callers with a clock (and tests) stay deterministic;
    it defaults to the current UTC time.
    """
    return (now or datetime.now(UTC)).year + PUB_YEAR_FUTURE_BUFFER
