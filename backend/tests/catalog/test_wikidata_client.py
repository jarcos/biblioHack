"""WikidataCanonSource keyset pagination — page threading, stop, guard.

No network: the HTTP page fetch is stubbed so we exercise only the pagination
control flow (cursor threading, partial-page stop, non-advancing-cursor guard).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bibliohack.catalog.infrastructure.wikidata.client import WikidataCanonSource

if TYPE_CHECKING:
    from bibliohack.catalog.domain.canon import CanonSeedWork


def _row(qid: str) -> dict[str, dict[str, str]]:
    return {
        "work": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "workLabel": {"value": f"Title {qid}"},
    }


class _StubSource(WikidataCanonSource):
    """Serves canned pages and records every query it was asked to run."""

    def __init__(self, pages: list[list[dict[str, Any]]], **kw: Any) -> None:
        super().__init__(user_agent="test", page_pause_seconds=0.0, **kw)
        self._pages = pages
        self.queries: list[str] = []

    async def _fetch_page(self, client: object, query: str) -> list[dict[str, Any]]:  # type: ignore[override]
        self.queries.append(query)
        return self._pages.pop(0) if self._pages else []


async def _collect(source: WikidataCanonSource, **kw: Any) -> list[CanonSeedWork]:
    return [w async for w in source.fetch_works(**kw)]


async def test_threads_keyset_cursor_across_pages() -> None:
    pages = [[_row("Q1"), _row("Q2")], [_row("Q3"), _row("Q4")], [_row("Q5")]]
    source = _StubSource(pages, page_size=2)
    works = await _collect(source)

    assert [w.source_ref for w in works] == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    # First page has no seek; subsequent pages seek past the previous page's max.
    assert "FILTER(STR(?work) >" not in source.queries[0]
    assert "Q2" in source.queries[1]
    assert "Q4" in source.queries[2]


async def test_partial_page_stops_iteration() -> None:
    # A page shorter than page_size is the last page — no further fetch.
    source = _StubSource([[_row("Q1")]], page_size=2)
    works = await _collect(source)
    assert [w.source_ref for w in works] == ["Q1"]
    assert len(source.queries) == 1


async def test_max_works_caps_emission() -> None:
    pages = [[_row("Q1"), _row("Q2")], [_row("Q3"), _row("Q4")]]
    source = _StubSource(pages, page_size=2)
    works = await _collect(source, max_works=3)
    assert [w.source_ref for w in works] == ["Q1", "Q2", "Q3"]


async def test_non_advancing_cursor_guards_against_infinite_loop() -> None:
    # Two identical full pages: the cursor can't advance, so iteration must stop
    # rather than re-request the same page forever.
    full_page = [_row("Q1"), _row("Q2")]
    source = _StubSource([list(full_page), list(full_page), list(full_page)], page_size=2)
    works = await _collect(source)
    # First page yields Q1,Q2; second page's cursor (Q2) equals the last → stop.
    assert [w.source_ref for w in works] == ["Q1", "Q2", "Q1", "Q2"]
    assert len(source.queries) == 2
