"""Postgres adapters: recommendation cache, shelf fingerprint, candidate engine.

Three small classes over one session:

- `PostgresRecommendationRepository` — the per-user cache (`recommendations`).
- `PostgresShelfTasteReader` — SHA-256 over the shelf's recommendation-relevant
  columns; the cache key that makes invalidation event-free.
- `PostgresCandidateRetriever` — the engine: average the embeddings of the
  user's best-loved matched books into a taste centroid (Python-side mean —
  a profile is ≤50 vectors, no need for in-DB aggregation), then pgvector
  cosine KNN over the catalogue, excluding the whole shelf, with the same
  literary scope filter search uses.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from bibliohack.catalog.domain.literary_profile import (
    default_scope_audiences,
    default_scope_forms,
)
from bibliohack.catalog.infrastructure.postgres.models import BibliographicRecordModel
from bibliohack.holdings.infrastructure.postgres.models import CopyModel
from bibliohack.reading_history.infrastructure.postgres.models import ShelfEntryModel
from bibliohack.recommendations.application.ports import (
    CachedBatch,
    Candidate,
    CandidateBatch,
    WeightedSignals,
)
from bibliohack.recommendations.domain.feedback import FeedbackSignal
from bibliohack.recommendations.domain.recommendation import Recommendation
from bibliohack.recommendations.infrastructure.postgres.models import (
    RecommendationFeedbackModel,
    RecommendationModel,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from bibliohack.catalog.application.ports import Embedder

# Profile size cap: enough signal for a stable centroid, small enough that
# one reader's giant shelf can't make profile-building expensive.
_MAX_PROFILE_BOOKS = 50

# Library-aware ranking (L4). In boost mode we pull a wider KNN pool, add a
# small bump to candidates borrowable in followed branches, then re-rank and
# trim — so nearby titles surface without letting library availability override
# taste similarity. Deliberately small, mirroring the canon relevance boost.
_LIBRARY_BOOST = 0.05
_POOL_FACTOR = 5
_MAX_POOL = 200

# Feedback → centroid weights (chat-recs P1, §4). Constants, not settings: tune
# them from impressions→reads data, never by intuition. `not_interested` carries
# no weight (it's "not now", not "not my taste") — it only hard-excludes. The
# `read_rating` weights (+1.2 / -0.6) arrive with P2's mark-read loop.
_FEEDBACK_WEIGHTS: dict[FeedbackSignal, float] = {
    FeedbackSignal.LIKE: 0.7,
    FeedbackSignal.MORE_LIKE_THIS: 0.7,
    FeedbackSignal.DISLIKE: -0.5,
    FeedbackSignal.NOT_INTERESTED: 0.0,
}
# Latest signals in these states are dropped from every batch, similarity aside.
_EXCLUDING_SIGNALS = frozenset({FeedbackSignal.DISLIKE, FeedbackSignal.NOT_INTERESTED})
# Stable digest for "this user has given no feedback" — keeps their cache key
# identical to the pre-P1 shelf fingerprint (no needless regeneration).
_EMPTY_FEEDBACK_HASH = ""


class PostgresRecommendationRepository:
    """Concrete `RecommendationRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_cached(self, user_id: str, cache_key: str) -> CachedBatch | None:
        rows = (
            (
                await self._session.execute(
                    select(RecommendationModel)
                    .where(
                        RecommendationModel.user_id == UUID(user_id),
                        RecommendationModel.cache_key == cache_key,
                    )
                    .order_by(RecommendationModel.score.desc())
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            # Distinguish "cached empty batch" from "no cache": an empty batch
            # is stored as zero rows, so probe whether ANY row exists for the
            # user with this key… zero rows is also genuinely no-cache. We
            # treat zero rows as no-cache; regenerating an empty batch is
            # cheap (the retriever short-circuits), so the ambiguity is fine.
            return None
        # Tastes are denormalised onto every row of a batch — read one.
        tastes = tuple(rows[0].inferred_tastes or ())
        return CachedBatch(
            recommendations=tuple(
                Recommendation(
                    record_id=str(row.matched_record_id),
                    score=row.score,
                    rationale=row.rationale,
                )
                for row in rows
            ),
            inferred_tastes=tastes,
        )

    async def replace(
        self,
        user_id: str,
        cache_key: str,
        recommendations: Sequence[Recommendation],
        *,
        inferred_tastes: Sequence[str] = (),
    ) -> None:
        await self._session.execute(
            delete(RecommendationModel).where(RecommendationModel.user_id == UUID(user_id))
        )
        tastes = list(inferred_tastes) or None
        for recommendation in recommendations:
            self._session.add(
                RecommendationModel(
                    id=uuid4(),
                    user_id=UUID(user_id),
                    matched_record_id=UUID(recommendation.record_id),
                    score=recommendation.score,
                    rationale=recommendation.rationale,
                    cache_key=cache_key,
                    inferred_tastes=tastes,
                )
            )
        await self._session.flush()


class PostgresFeedbackStore:
    """Concrete `FeedbackStore` — appends signals, reads latest-per-record state.

    The read side is a DISTINCT ON `(record_id)` ordered by `created_at desc`:
    the append-only log keeps history, but only the newest signal per record
    re-weights the centroid or busts the cache.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        user_id: str,
        record_id: str,
        signal: FeedbackSignal,
        *,
        rating: int | None = None,
    ) -> None:
        self._session.add(
            RecommendationFeedbackModel(
                id=uuid4(),
                user_id=UUID(user_id),
                record_id=UUID(record_id),
                signal=str(signal),
                rating=rating,
            )
        )
        await self._session.flush()

    async def _latest_signals(self, user_id: str) -> list[tuple[str, FeedbackSignal]]:
        """(record_id, latest signal) for every record the user has acted on."""
        rows = (
            await self._session.execute(
                select(
                    RecommendationFeedbackModel.record_id,
                    RecommendationFeedbackModel.signal,
                )
                .where(RecommendationFeedbackModel.user_id == UUID(user_id))
                .distinct(RecommendationFeedbackModel.record_id)
                .order_by(
                    RecommendationFeedbackModel.record_id,
                    RecommendationFeedbackModel.created_at.desc(),
                )
            )
        ).all()
        out: list[tuple[str, FeedbackSignal]] = []
        for row in rows:
            try:
                out.append((str(row.record_id), FeedbackSignal(row.signal)))
            except ValueError:
                continue  # unknown signal from a newer writer → ignore, don't crash
        return out

    async def state_hash(self, user_id: str) -> str:
        latest = await self._latest_signals(user_id)
        if not latest:
            return _EMPTY_FEEDBACK_HASH
        digest = hashlib.sha256(b"feedback\n")
        for record_id, signal in sorted(latest):
            digest.update(f"{record_id}|{signal}\n".encode())
        return digest.hexdigest()

    async def weighted_signals(self, user_id: str) -> WeightedSignals:
        latest = await self._latest_signals(user_id)
        weights: dict[str, float] = {}
        excluded: set[str] = set()
        for record_id, signal in latest:
            weight = _FEEDBACK_WEIGHTS.get(signal, 0.0)
            if weight:
                weights[record_id] = weight
            if signal in _EXCLUDING_SIGNALS:
                excluded.add(record_id)
        return WeightedSignals(weights=weights, excluded=frozenset(excluded))


class PostgresShelfTasteReader:
    """Concrete `ShelfTasteReader` — fingerprints the shelf state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def fingerprint(self, user_id: str) -> str | None:
        rows = (
            await self._session.execute(
                select(
                    ShelfEntryModel.source_book_id,
                    ShelfEntryModel.shelf,
                    ShelfEntryModel.rating,
                    ShelfEntryModel.matched_record_id,
                )
                .where(ShelfEntryModel.user_id == UUID(user_id))
                .order_by(ShelfEntryModel.source_book_id)
            )
        ).all()
        if not any(row.matched_record_id is not None for row in rows):
            return None  # no catalogue-matched books → no taste profile
        digest = hashlib.sha256()
        for row in rows:
            digest.update(
                f"{row.source_book_id}|{row.shelf}|{row.rating}|{row.matched_record_id}\n".encode()
            )
        return digest.hexdigest()

    async def raw_shelf(self, user_id: str) -> tuple[str, ...]:
        rows = (
            await self._session.execute(
                select(ShelfEntryModel.title, ShelfEntryModel.author)
                .where(ShelfEntryModel.user_id == UUID(user_id))
                .order_by(ShelfEntryModel.source_book_id)
            )
        ).all()
        return tuple(f"{row.title} — {row.author}" if row.author else row.title for row in rows)


class PostgresCandidateRetriever:
    """Concrete `CandidateRetriever` — centroid + cosine KNN.

    The optional `embedder` powers cold-start retrieval (§8.3.3): embedding an
    LLM-inferred taste descriptor when there's no shelf centroid to build from.
    Taste-based `retrieve` never needs it (it averages stored vectors).
    """

    def __init__(self, session: AsyncSession, *, embedder: Embedder | None = None) -> None:
        self._session = session
        self._embedder = embedder

    async def retrieve(
        self,
        user_id: str,
        *,
        limit: int,
        followed_branch_codes: list[str] | None = None,
        nearby_only: bool = False,
        feedback: WeightedSignals | None = None,
    ) -> CandidateBatch:
        owned_ids, profile_ids = await self._profile_record_ids(UUID(user_id))
        if not profile_ids:
            return CandidateBatch(liked_books=(), candidates=())

        anchors = (
            await self._session.execute(
                select(BibliographicRecordModel)
                .where(
                    BibliographicRecordModel.id.in_(profile_ids),
                    BibliographicRecordModel.embedding.is_not(None),
                )
                .options(selectinload(BibliographicRecordModel.contributors))
            )
        ).scalars()
        anchor_rows = list(anchors)
        if not anchor_rows:
            return CandidateBatch(liked_books=(), candidates=())  # embeddings not ready yet

        # Weighted centroid (chat-recs P1, §4): shelf anchors weigh +1.0 each,
        # then liked/disliked feedback records pull it toward / push it away.
        # The SQL filters embedding IS NOT NULL; the `if` repeats it for mypy.
        weighted = [(list(row.embedding), 1.0) for row in anchor_rows if row.embedding is not None]
        weighted += await self._feedback_vectors(feedback)
        centroid = _weighted_mean(weighted)
        liked_books = tuple(_label(row) for row in anchor_rows)

        # Every disliked / not-interested record is hard-dropped, on top of the
        # shelf itself (never recommend what's owned).
        excluded_ids = list(owned_ids)
        if feedback is not None and feedback.excluded:
            excluded_ids += [UUID(rid) for rid in feedback.excluded]

        distance = BibliographicRecordModel.embedding.cosine_distance(centroid)
        # "Held in a followed branch?" — a correlated EXISTS, present only when
        # the caller passed branches (drives the L4 boost / nearby-only filter).
        codes = followed_branch_codes or None
        held_expr = (
            select(CopyModel.id)
            .where(
                CopyModel.record_id == BibliographicRecordModel.id,
                CopyModel.is_active.is_(True),
                CopyModel.branch_code.in_(codes),
            )
            .exists()
            if codes
            else None
        )

        stmt = select(BibliographicRecordModel, distance.label("distance"))
        fetch_n = limit
        if held_expr is not None:
            stmt = stmt.add_columns(held_expr.label("held"))
            if nearby_only:
                stmt = stmt.where(held_expr)  # hard filter to borrowable-nearby
            else:
                # Boost mode: widen the pool so nearby titles a bit further down
                # the taste ranking can still surface after the bump.
                fetch_n = min(limit * _POOL_FACTOR, _MAX_POOL)
        stmt = (
            stmt.where(
                BibliographicRecordModel.embedding.is_not(None),
                BibliographicRecordModel.id.not_in(excluded_ids),
                BibliographicRecordModel.audience.in_(default_scope_audiences()),
                BibliographicRecordModel.literary_form.in_(default_scope_forms()),
            )
            .options(selectinload(BibliographicRecordModel.contributors))
            .order_by(distance.asc(), BibliographicRecordModel.titn.asc())
            .limit(fetch_n)
        )
        result = (await self._session.execute(stmt)).all()

        boosting = held_expr is not None and not nearby_only
        candidates = [
            Candidate(
                record_id=str(row.BibliographicRecordModel.id),
                title=row.BibliographicRecordModel.title,
                author=_first_author(row.BibliographicRecordModel),
                score=round(
                    min(
                        1.0,
                        max(0.0, 1.0 - float(row.distance))
                        + (_LIBRARY_BOOST if boosting and bool(row.held) else 0.0),
                    ),
                    4,
                ),
            )
            for row in result
        ]
        if boosting:
            # Re-rank by the boosted score and trim the widened pool to `limit`.
            candidates.sort(key=lambda c: c.score, reverse=True)
            candidates = candidates[:limit]
        return CandidateBatch(liked_books=liked_books, candidates=tuple(candidates))

    async def retrieve_cold_start(self, descriptor: str, *, limit: int) -> CandidateBatch:
        embedder = self._embedder  # local: keep the None-narrowing across the await
        if embedder is None or not descriptor.strip():
            return CandidateBatch(liked_books=(), candidates=())
        try:
            # Blocking HTTPS call (HF inference) — keep it off the event loop.
            vector = await asyncio.to_thread(embedder.embed_query, descriptor)
        except Exception as exc:  # degrade to empty-profile — never 500 a request
            structlog.get_logger().warning(
                "recommendations.cold_start_embed_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return CandidateBatch(liked_books=(), candidates=())
        if not vector:
            return CandidateBatch(liked_books=(), candidates=())

        distance = BibliographicRecordModel.embedding.cosine_distance(vector)
        stmt = (
            select(BibliographicRecordModel, distance.label("distance"))
            .where(
                BibliographicRecordModel.embedding.is_not(None),
                BibliographicRecordModel.audience.in_(default_scope_audiences()),
                BibliographicRecordModel.literary_form.in_(default_scope_forms()),
            )
            .options(selectinload(BibliographicRecordModel.contributors))
            .order_by(distance.asc(), BibliographicRecordModel.titn.asc())
            .limit(limit)
        )
        result = (await self._session.execute(stmt)).all()
        candidates = tuple(
            Candidate(
                record_id=str(row.BibliographicRecordModel.id),
                title=row.BibliographicRecordModel.title,
                author=_first_author(row.BibliographicRecordModel),
                score=round(max(0.0, 1.0 - float(row.distance)), 4),
            )
            for row in result
        )
        return CandidateBatch(liked_books=(), candidates=candidates)

    async def _feedback_vectors(
        self, feedback: WeightedSignals | None
    ) -> list[tuple[list[float], float]]:
        """(embedding, weight) for each liked/disliked feedback record (§4).

        Only records that carry a non-zero centroid weight are fetched
        (`not_interested` is exclusion-only). Records without an embedding yet
        are skipped — they still hard-exclude via `excluded`, they just can't
        move the centroid.
        """
        if feedback is None or not feedback.weights:
            return []
        ids = [UUID(rid) for rid in feedback.weights]
        rows = (
            await self._session.execute(
                select(BibliographicRecordModel.id, BibliographicRecordModel.embedding).where(
                    BibliographicRecordModel.id.in_(ids),
                    BibliographicRecordModel.embedding.is_not(None),
                )
            )
        ).all()
        return [
            (list(row.embedding), feedback.weights[str(row.id)])
            for row in rows
            if row.embedding is not None
        ]

    async def _profile_record_ids(self, user_id: UUID) -> tuple[list[UUID], list[UUID]]:
        """(everything matched on the shelf, the taste anchors).

        Anchors prefer loved books (rating ≥ 4); when none are rated that
        high, any matched book counts — a fresh import without ratings still
        gets recommendations. The full matched set is excluded from results
        either way (never recommend what's already on the shelf).
        """
        rows = (
            await self._session.execute(
                select(
                    ShelfEntryModel.matched_record_id,
                    ShelfEntryModel.rating,
                    ShelfEntryModel.date_read,
                    ShelfEntryModel.date_added,
                )
                .where(
                    ShelfEntryModel.user_id == user_id,
                    ShelfEntryModel.matched_record_id.is_not(None),
                )
                .order_by(
                    ShelfEntryModel.rating.desc().nullslast(),
                    ShelfEntryModel.date_read.desc().nullslast(),
                    ShelfEntryModel.date_added.desc().nullslast(),
                )
            )
        ).all()
        owned = [row.matched_record_id for row in rows]
        loved = [row.matched_record_id for row in rows if (row.rating or 0) >= 4]
        anchors = (loved or owned)[:_MAX_PROFILE_BOOKS]
        return owned, anchors


def _weighted_mean(weighted: list[tuple[list[float], float]]) -> list[float]:
    """Centroid as a weighted sum, scaled by total |weight| (§4).

    Cosine ranking ignores magnitude, so the divisor is only for numerical
    hygiene; the *direction* is what liked (+) and disliked (-) records bend.
    Falls back to the plain mean when every weight is +1.0 (no feedback), so
    a no-feedback user gets exactly today's centroid.
    """
    total = sum(abs(weight) for _, weight in weighted) or 1.0
    dimensions = len(weighted[0][0])
    sums = [0.0] * dimensions
    for vector, weight in weighted:
        for index, value in enumerate(vector):
            sums[index] += value * weight
    return [value / total for value in sums]


def _first_author(record: BibliographicRecordModel) -> str | None:
    return next((c.name for c in record.contributors if c.role == "author"), None)


def _label(record: BibliographicRecordModel) -> str:
    author = _first_author(record)
    return f"{record.title} — {author}" if author else record.title
