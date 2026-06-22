"""Unit tests for the SemanticSearch use case.

Verifies the use case embeds the query (off the event loop) and threads the
resulting vector into the read repository — without touching Postgres or HF.
Fakes stand in for both ports.
"""

from __future__ import annotations

import pytest

from bibliohack.catalog.application.dto import SearchPage
from bibliohack.catalog.application.use_cases.semantic_search import SemanticSearch
from bibliohack.catalog.domain.literary_profile import SearchScope

pytestmark = pytest.mark.asyncio


class _FakeEmbedder:
    """Records the text it was asked to embed and returns a fixed vector."""

    def __init__(self, vector: list[float]) -> None:
        self._vector = vector
        self.embedded: list[str] = []

    @property
    def dimensions(self) -> int:
        return len(self._vector)

    def embed_documents(self, texts: object) -> list[list[float]]:  # pragma: no cover
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        self.embedded.append(text)
        return self._vector


class _FakeReadRepo:
    """Captures the semantic_search call args and returns a canned page."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

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
        self.calls.append(
            {
                "query_vector": query_vector,
                "query": query,
                "limit": limit,
                "offset": offset,
                "scope": scope,
                "library_branch_codes": library_branch_codes,
            }
        )
        return SearchPage(query=query, items=(), total=0, limit=limit, offset=offset)


async def test_embeds_query_and_passes_vector_to_repo() -> None:
    embedder = _FakeEmbedder([0.1, 0.2, 0.3])
    repo = _FakeReadRepo()
    use_case = SemanticSearch(read_repo=repo, embedder=embedder)

    await use_case.execute(query="  amor en tiempos de guerra  ", limit=5, scope=SearchScope.ALL)

    # The query is stripped before embedding.
    assert embedder.embedded == ["amor en tiempos de guerra"]
    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert call["query_vector"] == [0.1, 0.2, 0.3]
    assert call["limit"] == 5
    assert call["scope"] is SearchScope.ALL
    # The original (unstripped) query is preserved for echo in the response.
    assert call["query"] == "  amor en tiempos de guerra  "


async def test_blank_query_short_circuits_without_embedding() -> None:
    embedder = _FakeEmbedder([1.0])
    repo = _FakeReadRepo()
    use_case = SemanticSearch(read_repo=repo, embedder=embedder)

    page = await use_case.execute(query="   ")

    assert page.items == ()
    assert page.total == 0
    # No embedding call, no repo call — we never spend an HF round-trip on noise.
    assert embedder.embedded == []
    assert repo.calls == []
