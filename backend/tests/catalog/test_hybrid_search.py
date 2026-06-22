"""Unit tests for the HybridSearch use case (RRF fusion of FTS + KNN).

Fakes behind both ports — no Postgres, no HuggingFace. Covers the fusion
maths, dedup, pagination over the fused pool, the blank-query short-circuit,
and the degrade-to-keyword path when the embedder errors.
"""

from __future__ import annotations

import pytest

from bibliohack.catalog.application.dto import CatalogRecordSummary, SearchPage
from bibliohack.catalog.application.use_cases.hybrid_search import HybridSearch, _rrf_fuse
from bibliohack.catalog.domain.literary_profile import SearchScope

pytestmark = pytest.mark.asyncio


def _summary(titn: int, *, relevance_score: float = 0.0) -> CatalogRecordSummary:
    return CatalogRecordSummary(
        titn=titn,
        title=f"Libro {titn}",
        authors=(),
        publisher=None,
        pub_year=None,
        copies_count=1,
        relevance_score=relevance_score,
    )


async def test_rrf_breaks_equal_fusion_ties_by_relevance() -> None:
    """D16: when two records earn the same RRF score at the same best rank,
    the higher catalogue relevance_score wins (it only breaks the tie)."""
    low = _summary(10, relevance_score=0.2)
    high = _summary(20, relevance_score=0.8)
    # Each appears once, at rank 1 of its own list → identical RRF score and
    # best_rank, so only relevance can order them.
    fused = _rrf_fuse((low,), (high,))
    assert [s.titn for s in fused] == [20, 10]


class _FakeEmbedder:
    def __init__(self, vector: list[float] | None = None, *, boom: bool = False) -> None:
        self._vector = vector if vector is not None else [0.1]
        self._boom = boom
        self.embedded: list[str] = []

    @property
    def dimensions(self) -> int:
        return len(self._vector)

    def embed_documents(self, texts: object) -> list[list[float]]:  # pragma: no cover
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        if self._boom:
            msg = "HF is having a moment"
            raise RuntimeError(msg)
        self.embedded.append(text)
        return self._vector


class _FakeReadRepo:
    """Returns canned ranked lists; records the calls it receives."""

    def __init__(
        self,
        keyword_titns: list[int],
        semantic_titns: list[int],
    ) -> None:
        self._keyword = keyword_titns
        self._semantic = semantic_titns
        self.search_calls: list[dict[str, object]] = []
        self.semantic_calls: list[dict[str, object]] = []

    async def search(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
        scope: SearchScope = SearchScope.LITERARY,
        library_branch_codes: list[str] | None = None,
    ) -> SearchPage:
        self.search_calls.append(
            {
                "query": query,
                "limit": limit,
                "offset": offset,
                "scope": scope,
                "library_branch_codes": library_branch_codes,
            }
        )
        items = tuple(_summary(t) for t in self._keyword)
        return SearchPage(query=query, items=items, total=len(items), limit=limit, offset=offset)

    async def semantic_search(
        self,
        *,
        query_vector: object,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
        scope: SearchScope = SearchScope.LITERARY,
        library_branch_codes: list[str] | None = None,
    ) -> SearchPage:
        self.semantic_calls.append(
            {
                "query_vector": query_vector,
                "limit": limit,
                "scope": scope,
                "library_branch_codes": library_branch_codes,
            }
        )
        items = tuple(_summary(t) for t in self._semantic)
        return SearchPage(query=query, items=items, total=len(items), limit=limit, offset=offset)


async def test_record_ranked_by_both_lists_wins() -> None:
    # 7 is mid-list in both rankings; 1 and 9 each lead only one list.
    # RRF: score(7) = 1/62 + 1/62 > score(1) = 1/61 > ... so 7 must fuse first.
    repo = _FakeReadRepo(keyword_titns=[1, 7, 3], semantic_titns=[9, 7, 5])
    page = await HybridSearch(read_repo=repo, embedder=_FakeEmbedder()).execute(query="guerra")

    titns = [item.titn for item in page.items]
    assert titns[0] == 7
    # Both single-list leaders follow, keyword's first (equal score, rank tie → titn).
    assert set(titns) == {1, 3, 5, 7, 9}
    assert page.total == 5
    assert titns[1:3] == [1, 9]


async def test_duplicates_are_fused_not_repeated() -> None:
    repo = _FakeReadRepo(keyword_titns=[1, 2], semantic_titns=[2, 1])
    page = await HybridSearch(read_repo=repo, embedder=_FakeEmbedder()).execute(query="x")

    titns = [item.titn for item in page.items]
    assert sorted(titns) == [1, 2]
    assert page.total == 2


async def test_pagination_slices_the_fused_pool() -> None:
    repo = _FakeReadRepo(keyword_titns=[1, 2, 3, 4], semantic_titns=[])
    page = await HybridSearch(read_repo=repo, embedder=_FakeEmbedder()).execute(
        query="x", limit=2, offset=2
    )

    assert [item.titn for item in page.items] == [3, 4]
    assert page.total == 4
    assert page.has_more is False


async def test_embedder_failure_degrades_to_keyword_ranking() -> None:
    repo = _FakeReadRepo(keyword_titns=[1, 2, 3], semantic_titns=[9])
    page = await HybridSearch(read_repo=repo, embedder=_FakeEmbedder(boom=True)).execute(query="x")

    # Semantic never ran; the keyword ranking survives untouched.
    assert repo.semantic_calls == []
    assert [item.titn for item in page.items] == [1, 2, 3]


async def test_blank_query_short_circuits() -> None:
    embedder = _FakeEmbedder()
    repo = _FakeReadRepo(keyword_titns=[1], semantic_titns=[1])
    page = await HybridSearch(read_repo=repo, embedder=embedder).execute(query="   ")

    assert page.items == ()
    assert page.total == 0
    assert embedder.embedded == []
    assert repo.search_calls == []


async def test_scope_threads_through_to_both_rankers() -> None:
    repo = _FakeReadRepo(keyword_titns=[1], semantic_titns=[2])
    await HybridSearch(read_repo=repo, embedder=_FakeEmbedder()).execute(
        query="x", scope=SearchScope.ALL
    )

    assert repo.search_calls[0]["scope"] is SearchScope.ALL
    assert repo.semantic_calls[0]["scope"] is SearchScope.ALL


async def test_library_scope_threads_through_to_both_rankers() -> None:
    repo = _FakeReadRepo(keyword_titns=[1], semantic_titns=[2])
    await HybridSearch(read_repo=repo, embedder=_FakeEmbedder()).execute(
        query="x", library_branch_codes=["AL03", "AL04"]
    )

    assert repo.search_calls[0]["library_branch_codes"] == ["AL03", "AL04"]
    assert repo.semantic_calls[0]["library_branch_codes"] == ["AL03", "AL04"]
