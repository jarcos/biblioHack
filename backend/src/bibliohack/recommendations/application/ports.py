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


@dataclass(frozen=True, slots=True)
class ColdStartProfile:
    """An LLM read of a brand-new user's shelf when nothing matched yet (§8.3.3).

    `descriptor` is a free-text taste summary we embed to retrieve candidates
    by meaning; `tastes` are short genre/topic phrases the UI shows as "we
    detected you like…" chips so the (necessarily weaker) cold-start batch is
    transparent about why it surfaced.
    """

    descriptor: str
    tastes: tuple[str, ...] = ()


class ShelfTasteReader(Protocol):
    """Reads the user's shelf as recommendation fuel."""

    async def fingerprint(self, user_id: str) -> str | None:
        """Stable hash of the shelf's recommendation-relevant state.

        Changes whenever entries/ratings/shelves change → cached rows expire.
        None when the user has no catalogue-matched books to build a taste
        profile from (nothing to recommend with).
        """
        ...

    async def raw_shelf(self, user_id: str) -> tuple[str, ...]:
        """Every shelf entry as "Title — Author", matched to the catalogue or not.

        The cold-start fuel: when `fingerprint` is None (no matched books) we
        still have the raw imported titles to infer taste from. Empty tuple
        only when the shelf itself is empty.
        """
        ...


class ColdStartClassifier(Protocol):
    """LLM taste extraction from a new user's raw shelf. Strictly best-effort."""

    async def infer(self, shelf_titles: Sequence[str]) -> ColdStartProfile | None:
        """A taste profile inferred from the titles, or None on any failure
        (so the caller falls back to today's empty-profile behaviour)."""
        ...


class CandidateRetriever(Protocol):
    """The engine: per-user profile → KNN over the shared catalogue."""

    async def retrieve(
        self,
        user_id: str,
        *,
        limit: int,
        followed_branch_codes: list[str] | None = None,
        nearby_only: bool = False,
    ) -> CandidateBatch:
        """Nearest unread records to the user's taste centroid.

        Excludes everything already on the user's shelf. Empty batch when
        the profile can't be built (no matched books / no embeddings yet).

        Library-aware (L4): when ``followed_branch_codes`` is given, records
        borrowable in those branches get a small score boost so they surface
        higher (taste still dominates). ``nearby_only`` turns that into a hard
        filter — only borrowable-nearby candidates. Both no-op when the list is
        empty/None.
        """
        ...

    async def retrieve_cold_start(self, descriptor: str, *, limit: int) -> CandidateBatch:
        """KNN over the catalogue from an inferred taste `descriptor` (§8.3.3).

        Used when the user has no catalogue-matched books to build a centroid
        from: the descriptor is embedded and ranked by cosine distance, with
        the same literary scope filter as taste-based retrieval. Empty batch
        when no embedder is available or embedding fails (the caller then
        degrades to the empty-profile response).
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
