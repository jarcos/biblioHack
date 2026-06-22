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

import hashlib
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from bibliohack.catalog.domain.literary_profile import (
    default_scope_audiences,
    default_scope_forms,
)
from bibliohack.catalog.infrastructure.postgres.models import BibliographicRecordModel
from bibliohack.holdings.infrastructure.postgres.models import CopyModel
from bibliohack.reading_history.infrastructure.postgres.models import ShelfEntryModel
from bibliohack.recommendations.application.ports import Candidate, CandidateBatch
from bibliohack.recommendations.domain.recommendation import Recommendation
from bibliohack.recommendations.infrastructure.postgres.models import RecommendationModel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

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


class PostgresRecommendationRepository:
    """Concrete `RecommendationRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_cached(self, user_id: str, cache_key: str) -> tuple[Recommendation, ...] | None:
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
        return tuple(
            Recommendation(
                record_id=str(row.matched_record_id),
                score=row.score,
                rationale=row.rationale,
            )
            for row in rows
        )

    async def replace(
        self, user_id: str, cache_key: str, recommendations: Sequence[Recommendation]
    ) -> None:
        await self._session.execute(
            delete(RecommendationModel).where(RecommendationModel.user_id == UUID(user_id))
        )
        for recommendation in recommendations:
            self._session.add(
                RecommendationModel(
                    id=uuid4(),
                    user_id=UUID(user_id),
                    matched_record_id=UUID(recommendation.record_id),
                    score=recommendation.score,
                    rationale=recommendation.rationale,
                    cache_key=cache_key,
                )
            )
        await self._session.flush()


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


class PostgresCandidateRetriever:
    """Concrete `CandidateRetriever` — centroid + cosine KNN."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def retrieve(
        self,
        user_id: str,
        *,
        limit: int,
        followed_branch_codes: list[str] | None = None,
        nearby_only: bool = False,
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

        # The SQL filters embedding IS NOT NULL; the `if` repeats it for mypy.
        centroid = _mean([list(row.embedding) for row in anchor_rows if row.embedding is not None])
        liked_books = tuple(_label(row) for row in anchor_rows)

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
                BibliographicRecordModel.id.not_in(owned_ids),
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


def _mean(vectors: list[list[float]]) -> list[float]:
    dimensions = len(vectors[0])
    sums = [0.0] * dimensions
    for vector in vectors:
        for index, value in enumerate(vector):
            sums[index] += value
    count = float(len(vectors))
    return [value / count for value in sums]


def _first_author(record: BibliographicRecordModel) -> str | None:
    return next((c.name for c in record.contributors if c.role == "author"), None)


def _label(record: BibliographicRecordModel) -> str:
    author = _first_author(record)
    return f"{record.title} — {author}" if author else record.title
