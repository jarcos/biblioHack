"""Recompute catalogue relevance for every record (Phase R, R2).

Orchestrates the nightly batch: gather raw signals for the whole corpus,
derive the corpus-wide normalisation bounds, score each record against them,
and write the scores back. Pure DB compute — no OPAC, no network — which is why
it runs on the crawl/worker plane (supercronic) rather than the request path.

The two-stage shape (gather everything → build corpus stats → score) is
inherent to corpus normalisation: a record's demand/holdings/recency are only
meaningful relative to the rest of the catalogue, so we need the whole set in
hand before any score is final.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bibliohack.catalog.domain.relevance import (
    RelevanceWeights,
    build_corpus_stats,
    score_record,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from bibliohack.catalog.infrastructure.postgres.relevance_repository import (
        PostgresRelevanceRepository,
    )


@dataclass(frozen=True, slots=True)
class RecomputeSummary:
    """What the run did, for CLI output + the Grafana coverage panel."""

    scored: int
    written: int
    cold_start: int
    window_days: int


class RecomputeRelevance:
    """Score the whole catalogue against its own corpus stats."""

    def __init__(
        self,
        *,
        repo: PostgresRelevanceRepository,
        weights: RelevanceWeights | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = repo
        self._weights = weights or RelevanceWeights()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, *, window_days: int = 90) -> RecomputeSummary:
        now = self._clock()
        signals = await self._repo.gather_signals(window_days=window_days)
        corpus = build_corpus_stats(signals)

        results = [(s.record_id, score_record(s, corpus, self._weights, now=now)) for s in signals]
        written = await self._repo.write_scores(results)  # type: ignore[arg-type]

        cold_start = sum(1 for s in signals if not s.has_history)
        return RecomputeSummary(
            scored=len(results),
            written=written,
            cold_start=cold_start,
            window_days=window_days,
        )
