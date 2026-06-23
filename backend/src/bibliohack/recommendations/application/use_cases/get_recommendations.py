"""GetRecommendations — cached when fresh, regenerated when the shelf moved.

Flow: fingerprint the shelf → serve the cache when the key still matches →
otherwise retrieve candidates (pgvector), decorate with LLM rationales
(best-effort: an LLM outage costs the prose, never the recommendations),
persist, serve. Per-user end to end: the profile is built from *this*
user's shelf and the result lands under their id only.

Cold-start (§8.3.3): when the shelf has no catalogue-matched books yet
(`fingerprint` is None), fall back to an LLM read of the raw imported titles —
a taste descriptor we embed to retrieve candidates by meaning. The outcome is
flagged `cold_start` so the UI can label its (weaker) confidence and show the
inferred tastes. A genuinely empty shelf, or an LLM/embedder outage, degrades
to the same `EMPTY_PROFILE` as before.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from bibliohack.recommendations.domain.recommendation import Recommendation
from bibliohack.shared.application.result import Err, Ok

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bibliohack.recommendations.application.ports import (
        CandidateBatch,
        CandidateRetriever,
        ColdStartClassifier,
        RationaleWriter,
        RecommendationRepository,
        ShelfTasteReader,
    )
    from bibliohack.shared.application.result import Result


class RecommendationsError(StrEnum):
    EMPTY_PROFILE = "empty_profile"


@dataclass(frozen=True, slots=True)
class RecommendationOutcome:
    """The use case's success payload.

    `recommendations` may be empty (profile exists but nothing retrievable yet).
    `cold_start` is True when the batch came from the LLM cold-start path rather
    than the taste centroid; `inferred_tastes` carries the genre/topic chips for
    that path (populated on fresh generation, empty on a cache hit — we don't
    persist them).
    """

    recommendations: tuple[Recommendation, ...]
    cold_start: bool = False
    inferred_tastes: tuple[str, ...] = field(default_factory=tuple)


class GetRecommendations:
    def __init__(
        self,
        *,
        shelf: ShelfTasteReader,
        retriever: CandidateRetriever,
        rationales: RationaleWriter,
        repository: RecommendationRepository,
        classifier: ColdStartClassifier,
        limit: int,
    ) -> None:
        self._shelf = shelf
        self._retriever = retriever
        self._rationales = rationales
        self._repository = repository
        self._classifier = classifier
        self._limit = limit

    async def execute(
        self,
        user_id: str,
        *,
        library_codes: list[str] | None = None,
        nearby_only: bool = False,
    ) -> Result[RecommendationOutcome, RecommendationsError]:
        fingerprint = await self._shelf.fingerprint(user_id)
        if fingerprint is None:
            return await self._cold_start(user_id)

        # The library context is part of the cache identity: changing followed
        # branches or toggling "nearby only" must regenerate (the batch ordering
        # depends on it). No context → the plain shelf fingerprint (back-compat).
        cache_key = _cache_key(fingerprint, library_codes, nearby_only)

        cached = await self._repository.get_cached(user_id, cache_key)
        if cached is not None:
            return Ok(RecommendationOutcome(recommendations=cached))

        batch = await self._retriever.retrieve(
            user_id,
            limit=self._limit,
            followed_branch_codes=library_codes,
            nearby_only=nearby_only,
        )
        if not batch.candidates:
            # Profile exists but nothing retrievable (e.g. embeddings still
            # catching up). Cache the emptiness too — the fingerprint will
            # bust it as soon as the shelf changes.
            await self._repository.replace(user_id, cache_key, ())
            return Ok(RecommendationOutcome(recommendations=()))

        recommendations = await self._decorate_and_store(
            user_id, cache_key, batch, batch.liked_books
        )
        return Ok(RecommendationOutcome(recommendations=recommendations))

    async def _cold_start(
        self, user_id: str
    ) -> Result[RecommendationOutcome, RecommendationsError]:
        """No catalogue-matched books: infer taste from the raw shelf (§8.3.3)."""
        raw_shelf = await self._shelf.raw_shelf(user_id)
        if not raw_shelf:
            return Err(RecommendationsError.EMPTY_PROFILE)  # genuinely empty shelf

        profile = await self._classifier.infer(raw_shelf)
        if profile is None:
            # LLM unavailable / no key → behave exactly as before.
            return Err(RecommendationsError.EMPTY_PROFILE)

        cache_key = _cold_start_cache_key(raw_shelf)
        cached = await self._repository.get_cached(user_id, cache_key)
        if cached is not None:
            # Tastes aren't persisted; the cold_start flag still drives the UI.
            return Ok(RecommendationOutcome(recommendations=cached, cold_start=True))

        batch = await self._retriever.retrieve_cold_start(profile.descriptor, limit=self._limit)
        if not batch.candidates:
            await self._repository.replace(user_id, cache_key, ())
            return Ok(
                RecommendationOutcome(
                    recommendations=(), cold_start=True, inferred_tastes=profile.tastes
                )
            )

        recommendations = await self._decorate_and_store(user_id, cache_key, batch, profile.tastes)
        return Ok(
            RecommendationOutcome(
                recommendations=recommendations,
                cold_start=True,
                inferred_tastes=profile.tastes,
            )
        )

    async def _decorate_and_store(
        self,
        user_id: str,
        cache_key: str,
        batch: CandidateBatch,
        liked_books: Sequence[str],
    ) -> tuple[Recommendation, ...]:
        """Add best-effort rationales, persist under `cache_key`, return the batch."""
        rationale_for = await self._rationales.write(
            liked_books=liked_books, candidates=batch.candidates
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
        return recommendations


def _cache_key(fingerprint: str, library_codes: list[str] | None, nearby_only: bool) -> str:
    """Shelf fingerprint, extended with the library context when there is one."""
    if not library_codes:
        return fingerprint
    digest = hashlib.sha256(fingerprint.encode())
    digest.update(f"|nearby={nearby_only}|".encode())
    for code in sorted(library_codes):
        digest.update(f"{code},".encode())
    return digest.hexdigest()


def _cold_start_cache_key(raw_shelf: Sequence[str]) -> str:
    """A cache key over the raw shelf titles, namespaced from taste fingerprints.

    Busts as soon as the imported titles change (e.g. a re-import or a new
    book), so a cold-start batch refreshes when the shelf does. 64-char hex,
    same column width as the taste fingerprint.
    """
    digest = hashlib.sha256(b"coldstart\n")
    for title in raw_shelf:
        digest.update(f"{title}\n".encode())
    return digest.hexdigest()
