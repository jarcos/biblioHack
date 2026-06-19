"""Postgres reads/writes for the catalogue relevance recompute (Phase R).

Two jobs, both set-based so the nightly recompute stays a single efficient
sweep rather than 37k round-trips:

- ``gather_signals`` — one pass over the availability time-series + holdings +
  the catalog/cover/subject/isbn tables, returning the raw per-record
  :class:`RecordSignals` the domain scorer needs. The demand arithmetic that
  turns raw counts into rates lives here (it's persistence-shaped: it depends
  on the snapshot window), but the *blend* lives in ``catalog.domain.relevance``.
- ``write_scores`` — bulk-update ``relevance_score`` / ``relevance_components``
  / ``relevance_updated_at`` from the scored results.

Demand is read off the availability series only (``unavailable``/``unknown``
snapshots are excluded as noise). Checkouts are ``available → loaned``
transitions detected with a per-copy ``LAG`` window over ``observed_at``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from bibliohack.catalog.domain.relevance import RecordSignals

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from bibliohack.catalog.domain.relevance import RelevanceResult


# One pass: holdings breadth, demand aggregates over the trailing window, and
# the completeness EXISTS flags. Demand counts come from a per-copy LAG so we
# can spot available→loaned checkout transitions; `_recent` mirrors the same
# count over the second half of the window for the trending sub-signal.
_GATHER_SQL = text(
    """
WITH win AS (
    SELECT
        c.record_id,
        s.observed_at,
        s.status,
        LAG(s.status) OVER (PARTITION BY s.copy_id ORDER BY s.observed_at) AS prev_status
    FROM availability_snapshots s
    JOIN copies c ON c.id = s.copy_id
    WHERE s.observed_at >= :window_start
),
demand AS (
    SELECT
        record_id,
        COALESCE(
            SUM(CASE WHEN status IN ('loaned', 'reserved') THEN 1 ELSE 0 END)::float
            / NULLIF(SUM(CASE WHEN status IN ('available', 'loaned', 'reserved')
                             THEN 1 ELSE 0 END), 0),
            0.0
        ) AS scarcity,
        SUM(CASE WHEN prev_status = 'available' AND status = 'loaned'
                 THEN 1 ELSE 0 END) AS checkouts,
        SUM(CASE WHEN prev_status = 'available' AND status = 'loaned'
                 AND observed_at >= :window_mid THEN 1 ELSE 0 END) AS checkouts_recent,
        MIN(observed_at) AS first_obs,
        MAX(observed_at) AS last_obs,
        COUNT(*) AS n_obs
    FROM win
    GROUP BY record_id
),
holdings AS (
    SELECT
        record_id,
        COUNT(*) FILTER (WHERE is_active) AS copies,
        COUNT(DISTINCT branch_code) FILTER (WHERE is_active) AS branches
    FROM copies
    GROUP BY record_id
),
canon AS (
    -- One row per record the canon seed matched (C2). A record may match more
    -- than one seed work (a work + an edition); take the strongest signal.
    SELECT
        matched_record_id AS record_id,
        MAX(notability) AS canon_notability,
        MAX(COALESCE(array_length(awards, 1), 0)) AS canon_award_count
    FROM canon_seed
    WHERE matched_record_id IS NOT NULL
    GROUP BY matched_record_id
)
SELECT
    r.id AS record_id,
    r.pub_year,
    r.first_seen_at,
    (r.summary IS NOT NULL AND length(btrim(r.summary)) > 0) AS has_summary,
    EXISTS (SELECT 1 FROM isbns i WHERE i.record_id = r.id) AS has_isbn,
    EXISTS (SELECT 1 FROM subjects sub WHERE sub.record_id = r.id) AS has_subjects,
    EXISTS (
        SELECT 1 FROM isbns i
        JOIN covers cv ON cv.isbn_13 = i.isbn
        WHERE i.record_id = r.id AND cv.status = 'resolved'
    ) AS has_cover,
    COALESCE(h.copies, 0) AS copies,
    COALESCE(h.branches, 0) AS branches,
    d.scarcity,
    d.checkouts,
    d.checkouts_recent,
    d.first_obs,
    d.last_obs,
    COALESCE(d.n_obs, 0) AS n_obs,
    (cn.record_id IS NOT NULL) AS is_canon,
    COALESCE(cn.canon_notability, 0) AS canon_notability,
    COALESCE(cn.canon_award_count, 0) AS canon_award_count
FROM bibliographic_records r
LEFT JOIN holdings h ON h.record_id = r.id
LEFT JOIN demand d ON d.record_id = r.id
LEFT JOIN canon cn ON cn.record_id = r.id
"""
)

# Minimum span (weeks) we divide velocity by, so a burst inside a sub-week
# window can't produce an absurd per-week rate.
_MIN_VELOCITY_WEEKS = 1.0


class PostgresRelevanceRepository:
    """Gather raw relevance signals and write the computed scores back."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def gather_signals(self, *, window_days: int) -> list[RecordSignals]:
        """One-pass read of every record's raw relevance signals."""
        now = datetime.now(UTC)
        window_start = now - timedelta(days=window_days)
        window_mid = now - timedelta(days=window_days / 2)

        rows = (
            await self._session.execute(
                _GATHER_SQL,
                {"window_start": window_start, "window_mid": window_mid},
            )
        ).mappings()

        return [_row_to_signals(row) for row in rows]

    async def write_scores(self, results: Sequence[tuple[UUID, RelevanceResult]]) -> int:
        """Bulk-write scores/components/updated_at. Returns rows touched."""
        if not results:
            return 0
        now = datetime.now(UTC)
        stmt = text(
            """
                UPDATE bibliographic_records
                SET relevance_score = :score,
                    relevance_components = :components,
                    relevance_updated_at = :updated_at
                WHERE id = :record_id
                """
        ).bindparams(bindparam("components", type_=JSONB))
        params = [
            {
                "record_id": record_id,
                "score": result.score,
                "components": result.components,
                "updated_at": now,
            }
            for record_id, result in results
        ]
        await self._session.execute(stmt, params)
        return len(params)


def _row_to_signals(row: object) -> RecordSignals:
    """Turn one SQL row into raw domain signals, computing per-week rates.

    Rate arithmetic (counts → per-copy-per-week velocity) lives here because it
    depends on the snapshot window shape; the scoring *blend* stays in the
    domain. A record with no usable snapshots is flagged ``has_history=False``
    so the domain applies the neutral cold-start demand.
    """
    m = row  # SQLAlchemy RowMapping (dict-like)
    copies: int = m["copies"]  # type: ignore[index]
    branches: int = m["branches"]  # type: ignore[index]
    n_obs: int = m["n_obs"]  # type: ignore[index]

    has_history = n_obs > 0 and copies > 0
    observation_weeks = 0.0
    weekly_velocity = 0.0
    baseline_velocity = 0.0
    scarcity = 0.0

    if has_history:
        scarcity = float(m["scarcity"] or 0.0)  # type: ignore[index]
        first_obs = m["first_obs"]  # type: ignore[index]
        last_obs = m["last_obs"]  # type: ignore[index]
        span_days = max(0.0, (last_obs - first_obs).total_seconds() / 86400.0)
        observation_weeks = span_days / 7.0

        checkouts = int(m["checkouts"] or 0)  # type: ignore[index]
        checkouts_recent = int(m["checkouts_recent"] or 0)  # type: ignore[index]
        checkouts_baseline = max(0, checkouts - checkouts_recent)

        weeks = max(observation_weeks, _MIN_VELOCITY_WEEKS)
        weekly_velocity = checkouts / (copies * weeks)
        # Baseline = first-half rate; the overall vs first-half ratio reads as
        # acceleration in the trending sub-signal. Half the window's weeks.
        half_weeks = max(observation_weeks / 2.0, _MIN_VELOCITY_WEEKS)
        baseline_velocity = checkouts_baseline / (copies * half_weeks)

    return RecordSignals(
        record_id=m["record_id"],  # type: ignore[index]
        has_history=has_history,
        observation_weeks=observation_weeks,
        scarcity=scarcity,
        weekly_velocity=weekly_velocity,
        baseline_velocity=baseline_velocity,
        copies=copies,
        branches=branches,
        pub_year=m["pub_year"],  # type: ignore[index]
        first_seen_at=m["first_seen_at"],  # type: ignore[index]
        has_cover=bool(m["has_cover"]),  # type: ignore[index]
        has_summary=bool(m["has_summary"]),  # type: ignore[index]
        has_isbn=bool(m["has_isbn"]),  # type: ignore[index]
        has_subjects=bool(m["has_subjects"]),  # type: ignore[index]
        is_canon=bool(m["is_canon"]),  # type: ignore[index]
        canon_notability=int(m["canon_notability"] or 0),  # type: ignore[index]
        canon_award_count=int(m["canon_award_count"] or 0),  # type: ignore[index]
    )
