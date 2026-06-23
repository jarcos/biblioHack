"""RewriteAwareSearch unit tests — in-memory fakes, no DB, no network.

Pins the orchestration contract: the heuristic gate, structured→browse
routing, the zero-result fallback, and the cleaned-query free-text path.
"""

from __future__ import annotations

import pytest

from bibliohack.catalog.application.dto import (
    BrowsePage,
    CatalogRecordSummary,
    RewrittenQuery,
    SearchPage,
)
from bibliohack.catalog.application.use_cases.rewrite_aware_search import (
    RewriteAwareSearch,
    should_rewrite,
)


def _summary(titn: int, title: str) -> CatalogRecordSummary:
    return CatalogRecordSummary(
        titn=titn, title=title, authors=(), publisher=None, pub_year=None, copies_count=0
    )


class _FakeRepo:
    """Records the last browse/search call and returns canned pages."""

    def __init__(self, *, browse_items: tuple[CatalogRecordSummary, ...]) -> None:
        self._browse_items = browse_items
        self.browse_kwargs: dict[str, object] | None = None
        self.search_kwargs: dict[str, object] | None = None

    async def browse(self, **kwargs: object) -> BrowsePage:
        self.browse_kwargs = kwargs
        return BrowsePage(
            items=self._browse_items,
            total=len(self._browse_items),
            limit=int(kwargs.get("limit", 20)),  # type: ignore[arg-type]
            offset=int(kwargs.get("offset", 0)),  # type: ignore[arg-type]
            facets={},
        )

    async def search(self, **kwargs: object) -> SearchPage:
        self.search_kwargs = kwargs
        return SearchPage(
            query=str(kwargs.get("query", "")),
            items=(_summary(99, "literal hit"),),
            total=1,
            limit=int(kwargs.get("limit", 20)),  # type: ignore[arg-type]
            offset=int(kwargs.get("offset", 0)),  # type: ignore[arg-type]
        )


class _FakeRewriter:
    def __init__(self, result: RewrittenQuery | None) -> None:
        self._result = result
        self.calls = 0

    async def rewrite(self, query: str) -> RewrittenQuery | None:
        self.calls += 1
        return self._result


# ── should_rewrite heuristic ───────────────────────────────────


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Sapiens", False),
        ("García Márquez", False),
        ("la sombra del viento", True),  # 4 words
        ("lo último de Sapiens", True),  # NL cue
        ("¿qué leer este verano?", True),  # question
        ("libros de Cela", True),  # NL cue, short
    ],
)
def test_should_rewrite_heuristic(query: str, expected: bool) -> None:
    assert should_rewrite(query) is expected


# ── orchestration ──────────────────────────────────────────────


async def test_structured_rewrite_routes_to_browse() -> None:
    repo = _FakeRepo(browse_items=(_summary(1, "Sapiens"),))
    rewriter = _FakeRewriter(RewrittenQuery(author="Yuval Noah Harari", sort="newest"))

    page, applied = await RewriteAwareSearch(
        read_repo=repo, embedder=None, rewriter=rewriter
    ).execute(query="lo último de Sapiens")

    assert applied is not None
    assert applied.author == "Yuval Noah Harari"
    assert [i.titn for i in page.items] == [1]
    assert repo.browse_kwargs is not None
    assert repo.browse_kwargs["author"] == "Yuval Noah Harari"
    assert repo.browse_kwargs["sort"] == "newest"
    assert repo.search_kwargs is None  # never touched the free-text path


async def test_zero_result_browse_falls_back_to_literal() -> None:
    repo = _FakeRepo(browse_items=())  # browse finds nothing
    rewriter = _FakeRewriter(RewrittenQuery(author="Nadie Existente"))

    page, applied = await RewriteAwareSearch(
        read_repo=repo, embedder=None, rewriter=rewriter
    ).execute(query="lo último de Nadie Existente")

    assert applied is None  # rewrite was abandoned
    assert repo.search_kwargs is not None  # literal search ran
    assert page.items[0].titn == 99


async def test_short_query_skips_the_llm() -> None:
    repo = _FakeRepo(browse_items=(_summary(1, "x"),))
    rewriter = _FakeRewriter(RewrittenQuery(author="Should Not Be Used"))

    _page, applied = await RewriteAwareSearch(
        read_repo=repo, embedder=None, rewriter=rewriter
    ).execute(query="Sapiens")

    assert rewriter.calls == 0  # heuristic gated it out
    assert applied is None
    assert repo.search_kwargs is not None
    assert repo.search_kwargs["query"] == "Sapiens"


async def test_rewriter_returns_none_runs_literal() -> None:
    repo = _FakeRepo(browse_items=())
    rewriter = _FakeRewriter(None)

    _page, applied = await RewriteAwareSearch(
        read_repo=repo, embedder=None, rewriter=rewriter
    ).execute(query="algo que no se puede interpretar")

    assert rewriter.calls == 1
    assert applied is None
    assert repo.search_kwargs is not None


async def test_cleaned_query_only_applied_silently() -> None:
    repo = _FakeRepo(browse_items=())
    rewriter = _FakeRewriter(RewrittenQuery(cleaned_query="misterio Sevilla"))

    _page, applied = await RewriteAwareSearch(
        read_repo=repo, embedder=None, rewriter=rewriter
    ).execute(query="novelas de misterio ambientadas en Sevilla")

    assert applied is None  # nothing structured → no chip
    assert repo.search_kwargs is not None
    assert repo.search_kwargs["query"] == "misterio Sevilla"  # cleaned text used
