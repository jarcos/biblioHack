"""Hybrid search use case — Reciprocal Rank Fusion of FTS and vector KNN.

Keyword search (ts_rank_cd over the spanish_unaccent tsquery) is precise on
literal terms but blind to meaning; semantic KNN (BGE-M3 cosine) finds
meaning but can drift on exact titles and proper names. RRF fuses the two
rankings without having to calibrate their incomparable scores: each record
earns 1 / (k + rank) per list it appears in, and appearing high in *both*
lists compounds. The constant k=60 is the original RRF paper's default and
deliberately not tunable here — sensitivity to it is low.

Mechanics: both rankers contribute a fixed candidate pool (top-`_POOL` each,
offset 0); fusion happens in process over the summaries' TITNs; the requested
page is then sliced out of the fused list. Consequences worth knowing:

- `total` is the size of the *fused candidate pool* (at most 2·_POOL), not the
  corpus-wide match count — hybrid pagination is bounded by the pool. Deep
  pagination belongs to the single-ranker modes.
- The two repository calls run sequentially (one AsyncSession — concurrent
  queries on a session are not allowed); only the HF embedding round-trip
  overlaps the keyword query, since it needs no session.
- If the embedder errors (HF hiccup), we log and degrade to the keyword
  ranking rather than failing the search — same fail-open philosophy as the
  rate limiter.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from bibliohack.catalog.domain.literary_profile import SearchScope

if TYPE_CHECKING:
    from bibliohack.catalog.application.dto import CatalogRecordSummary, SearchPage
    from bibliohack.catalog.application.ports import Embedder

_POOL = 50  # candidates contributed by each ranker
_RRF_K = 60  # standard RRF constant


class HybridSearch:
    """Fuse keyword and semantic rankings with Reciprocal Rank Fusion."""

    def __init__(self, *, read_repo: object, embedder: Embedder) -> None:
        # `read_repo` is a CatalogReadRepository; typed loosely to avoid a
        # runtime import of the Protocol (same pattern as SemanticSearch).
        self._read_repo = read_repo
        self._embedder = embedder

    async def execute(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
        scope: SearchScope = SearchScope.LITERARY,
        library_branch_codes: list[str] | None = None,
    ) -> SearchPage:
        from bibliohack.catalog.application.dto import SearchPage

        cleaned = query.strip()
        if not cleaned:
            return SearchPage(query=query, items=(), total=0, limit=limit, offset=offset)

        # Embedding needs no DB session, so it overlaps the keyword query.
        embed_task = asyncio.create_task(self._embed_or_none(cleaned))
        keyword_page: SearchPage = await self._read_repo.search(  # type: ignore[attr-defined]
            query=query,
            limit=_POOL,
            offset=0,
            scope=scope,
            library_branch_codes=library_branch_codes,
        )
        vector = await embed_task

        semantic_items: tuple[CatalogRecordSummary, ...] = ()
        if vector:
            semantic_page: SearchPage = await self._read_repo.semantic_search(  # type: ignore[attr-defined]
                query_vector=vector,
                query=query,
                limit=_POOL,
                offset=0,
                scope=scope,
                library_branch_codes=library_branch_codes,
            )
            semantic_items = semantic_page.items

        fused = _rrf_fuse(keyword_page.items, semantic_items)
        return SearchPage(
            query=query,
            items=tuple(fused[offset : offset + limit]),
            total=len(fused),
            limit=limit,
            offset=offset,
        )

    async def _embed_or_none(self, text: str) -> list[float] | None:
        """The query vector, or None when HF is having a moment (fail open)."""
        try:
            # Blocking HTTPS call — keep it off the event loop.
            return await asyncio.to_thread(self._embedder.embed_query, text)
        except Exception as exc:  # degrade to keyword — never 500 a search
            structlog.get_logger().warning(
                "hybrid_search.embedding_failed_degrading_to_keyword",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None


def _rrf_fuse(
    *rankings: tuple[CatalogRecordSummary, ...],
) -> list[CatalogRecordSummary]:
    """Reciprocal Rank Fusion over ranked summary lists, deduped by TITN.

    The fused RRF score drives the order; ties break on best single-list rank,
    then on catalogue `relevance_score` (D16 — relevance only breaks near-ties,
    never out-ranks a stronger fused match), then titn for determinism.
    """
    scores: dict[int, float] = {}
    best_rank: dict[int, int] = {}
    first_seen: dict[int, CatalogRecordSummary] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item.titn] = scores.get(item.titn, 0.0) + 1.0 / (_RRF_K + rank)
            best_rank[item.titn] = min(best_rank.get(item.titn, rank), rank)
            first_seen.setdefault(item.titn, item)
    ordered = sorted(
        scores,
        key=lambda titn: (
            -scores[titn],
            best_rank[titn],
            -first_seen[titn].relevance_score,
            titn,
        ),
    )
    return [first_seen[titn] for titn in ordered]
