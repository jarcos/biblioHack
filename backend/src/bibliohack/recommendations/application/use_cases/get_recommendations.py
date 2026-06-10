"""GetRecommendations — cached when fresh, regenerated when the shelf moved.

Flow: fingerprint the shelf → serve the cache when the key still matches →
otherwise retrieve candidates (pgvector), decorate with LLM rationales
(best-effort: an LLM outage costs the prose, never the recommendations),
persist, serve. Per-user end to end: the profile is built from *this*
user's shelf and the result lands under their id only.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from bibliohack.recommendations.domain.recommendation import Recommendation
from bibliohack.shared.application.result import Err, Ok

if TYPE_CHECKING:
    from bibliohack.recommendations.application.ports import (
        CandidateRetriever,
        RationaleWriter,
        RecommendationRepository,
        ShelfTasteReader,
    )
    from bibliohack.shared.application.result import Result


class RecommendationsError(StrEnum):
    EMPTY_PROFILE = "empty_profile"


class GetRecommendations:
    def __init__(
        self,
        *,
        shelf: ShelfTasteReader,
        retriever: CandidateRetriever,
        rationales: RationaleWriter,
        repository: RecommendationRepository,
        limit: int,
    ) -> None:
        self._shelf = shelf
        self._retriever = retriever
        self._rationales = rationales
        self._repository = repository
        self._limit = limit

    async def execute(
        self, user_id: str
    ) -> Result[tuple[Recommendation, ...], RecommendationsError]:
        cache_key = await self._shelf.fingerprint(user_id)
        if cache_key is None:
            return Err(RecommendationsError.EMPTY_PROFILE)

        cached = await self._repository.get_cached(user_id, cache_key)
        if cached is not None:
            return Ok(cached)

        batch = await self._retriever.retrieve(user_id, limit=self._limit)
        if not batch.candidates:
            # Profile exists but nothing retrievable (e.g. embeddings still
            # catching up). Cache the emptiness too — the fingerprint will
            # bust it as soon as the shelf changes.
            await self._repository.replace(user_id, cache_key, ())
            return Ok(())

        rationale_for = await self._rationales.write(
            liked_books=batch.liked_books, candidates=batch.candidates
        )
        recommendations = tuple(
            Recommendation(
                record_id=candidate.record_id,
                score=candidate.score,
                rationale=rationale_for.get(candidate.record_id),
            )
            for candidate in batch.candidates
        )
        await self._repository.replace(user_id, cache_key, recommendations)
        return Ok(recommendations)
