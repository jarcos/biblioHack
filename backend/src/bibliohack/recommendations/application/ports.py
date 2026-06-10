"""Ports for the recommendations context.

The use case composes four abilities: fingerprint the user's shelf (cache
invalidation), retrieve candidates (the pgvector engine), write rationales
(the LLM, best-effort) and persist the result. Tests substitute in-memory
fakes; identifiers cross as plain strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bibliohack.recommendations.domain.recommendation import Recommendation


@dataclass(frozen=True, slots=True)
class Candidate:
    """A retrieved catalogue record, with the context the LLM prompt needs."""

    record_id: str
    title: str
    author: str | None
    score: float


@dataclass(frozen=True, slots=True)
class CandidateBatch:
    """Retriever output: the user's taste anchors + the scored candidates."""

    liked_books: tuple[str, ...]  # "Title — Author" of the profile anchors
    candidates: tuple[Candidate, ...]


class ShelfTasteReader(Protocol):
    """Reads the user's shelf as recommendation fuel."""

    async def fingerprint(self, user_id: str) -> str | None:
        """Stable hash of the shelf's recommendation-relevant state.

        Changes whenever entries/ratings/shelves change → cached rows expire.
        None when the user has no catalogue-matched books to build a taste
        profile from (nothing to recommend with).
        """
        ...


class CandidateRetriever(Protocol):
    """The engine: per-user profile → KNN over the shared catalogue."""

    async def retrieve(self, user_id: str, *, limit: int) -> CandidateBatch:
        """Nearest unread records to the user's taste centroid.

        Excludes everything already on the user's shelf. Empty batch when
        the profile can't be built (no matched books / no embeddings yet).
        """
        ...


class RationaleWriter(Protocol):
    """Optional LLM color ("why this book, for you"). Strictly best-effort."""

    async def write(
        self, *, liked_books: Sequence[str], candidates: Sequence[Candidate]
    ) -> dict[str, str]:
        """record_id → one-sentence rationale. Empty dict on any failure."""
        ...


class RecommendationRepository(Protocol):
    """Per-user cache of generated recommendations."""

    async def get_cached(self, user_id: str, cache_key: str) -> tuple[Recommendation, ...] | None:
        """The cached batch for this exact shelf state, or None (stale/absent)."""
        ...

    async def replace(
        self, user_id: str, cache_key: str, recommendations: Sequence[Recommendation]
    ) -> None:
        """Drop the user's previous batch and store this one."""
        ...
