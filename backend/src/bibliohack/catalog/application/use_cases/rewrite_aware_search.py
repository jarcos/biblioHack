"""Rewrite-aware search — natural language in, structured results out (§8.3.1).

Wraps the ordinary search with one optional step: when the query *looks* like
natural language, ask the LLM to parse it into structured intent (author / year
range / sort). If it extracts real filters, run a faceted browse with them;
otherwise fall back to a plain keyword / semantic / hybrid search.

Three deliberate safety nets keep this from ever making search worse:

- A cheap local heuristic (`should_rewrite`) gates the LLM call, so a one-word
  title or author never pays the round-trip (or the OpenRouter budget).
- The rewriter is best-effort: any failure returns None and we run the literal
  query.
- A rewritten browse that returns nothing falls back to the literal search,
  so a mis-parsed author can't strand the user on an empty page.

`execute` returns the page plus the *applied* intent (or None) so the API can
show a revertible "showing results for…" chip.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from bibliohack.catalog.application.use_cases.hybrid_search import HybridSearch
from bibliohack.catalog.application.use_cases.semantic_search import SemanticSearch
from bibliohack.catalog.domain.literary_profile import SearchScope

if TYPE_CHECKING:
    from bibliohack.catalog.application.dto import RewrittenQuery, SearchPage
    from bibliohack.catalog.application.ports import Embedder, QueryRewriter

# Spanish (and a few English) cues that a query is a phrase to interpret rather
# than a literal title/author lookup. Word-boundary matched, accent-insensitive
# enough for the common cases.
_NL_CUES = (
    "lo ultimo",
    "lo último",
    "lo nuevo",
    "libros de",
    "libros sobre",
    "libro de",
    "libro sobre",
    "novelas de",
    "novela de",
    "obras de",
    "parecido a",
    "parecidos a",
    "similar a",
    "similares a",
    "como ",
    "del autor",
    "de la autora",
    "ordenad",
    "mas reciente",
    "más reciente",
    "mas nuevo",
    "más nuevo",
    "que tratan",
    "que traten",
    "que hablen",
    "recomienda",
    "recomiénda",
    "busco ",
    "quiero ",
    "algo de",
    "sobre ",
    "ambientad",
    "escritos por",
    "escrito por",
)

# Below this word count a query is almost certainly a title/author — skip the
# LLM entirely.
_MIN_WORDS_FOR_NL = 4


def should_rewrite(query: str) -> bool:
    """True when `query` reads like natural language worth rewriting.

    Pure and cheap (no I/O) so it can gate the LLM call for free. Fires on an
    explicit NL cue, a trailing question mark, or simply a longer multi-word
    phrase. Short keyword queries return False and search runs literally.
    """
    cleaned = query.strip().lower()
    if not cleaned:
        return False
    if cleaned.endswith("?") or cleaned.startswith("¿"):
        return True
    if any(cue in cleaned for cue in _NL_CUES):
        return True
    return len(re.findall(r"\w+", cleaned)) >= _MIN_WORDS_FOR_NL


class RewriteAwareSearch:
    """Search that first tries to interpret a natural-language query."""

    def __init__(
        self,
        *,
        read_repo: object,  # PostgresCatalogReadRepository (loose, as in HybridSearch)
        embedder: Embedder | None,
        rewriter: QueryRewriter,
    ) -> None:
        self._read_repo = read_repo
        self._embedder = embedder
        self._rewriter = rewriter

    async def execute(
        self,
        *,
        query: str,
        mode: str = "keyword",
        limit: int = 20,
        offset: int = 0,
        scope: SearchScope = SearchScope.LITERARY,
        library_branch_codes: list[str] | None = None,
    ) -> tuple[SearchPage, RewrittenQuery | None]:
        rewritten: RewrittenQuery | None = None
        if should_rewrite(query):
            rewritten = await self._rewriter.rewrite(query)

        if rewritten is not None and rewritten.is_structured:
            page = await self._browse_as_search(
                rewritten, limit=limit, offset=offset, library_branch_codes=library_branch_codes
            )
            if page.total > 0:
                return page, rewritten
            # Mis-parse (e.g. wrong author) → don't strand on an empty page.
            rewritten = None

        # Free-text path: use the cleaned query when the rewrite produced one,
        # else the original. A cleaned-only rewrite is applied silently (no
        # structured chip to show), so we report None as the applied intent.
        text = rewritten.cleaned_query if rewritten and rewritten.cleaned_query else query
        page = await self._free_text_search(
            text,
            mode=mode,
            limit=limit,
            offset=offset,
            scope=scope,
            library_branch_codes=library_branch_codes,
        )
        return page, None

    async def _browse_as_search(
        self,
        rewritten: RewrittenQuery,
        *,
        limit: int,
        offset: int,
        library_branch_codes: list[str] | None,
    ) -> SearchPage:
        """Run the structured intent as a faceted browse, shaped as a SearchPage."""
        from bibliohack.catalog.application.dto import SearchPage

        browse_page = await self._read_repo.browse(  # type: ignore[attr-defined]
            author=rewritten.author,
            year_from=rewritten.year_from,
            year_to=rewritten.year_to,
            sort=rewritten.sort or "relevance",
            limit=limit,
            offset=offset,
            library_branch_codes=library_branch_codes,
        )
        return SearchPage(
            query=rewritten.author or "",
            items=browse_page.items,
            total=browse_page.total,
            limit=browse_page.limit,
            offset=browse_page.offset,
        )

    async def _free_text_search(
        self,
        text: str,
        *,
        mode: str,
        limit: int,
        offset: int,
        scope: SearchScope,
        library_branch_codes: list[str] | None,
    ) -> SearchPage:
        """The ordinary keyword / semantic / hybrid search (embedder-gated)."""
        if mode == "hybrid" and self._embedder is not None:
            return await HybridSearch(read_repo=self._read_repo, embedder=self._embedder).execute(
                query=text,
                limit=limit,
                offset=offset,
                scope=scope,
                library_branch_codes=library_branch_codes,
            )
        if mode == "semantic" and self._embedder is not None:
            return await SemanticSearch(read_repo=self._read_repo, embedder=self._embedder).execute(
                query=text,
                limit=limit,
                offset=offset,
                scope=scope,
                library_branch_codes=library_branch_codes,
            )
        # Assign to a typed local (not a bare return) so the Any from the
        # loosely-typed read_repo lands in SearchPage rather than tripping
        # no-any-return — same pattern as HybridSearch.
        page: SearchPage = await self._read_repo.search(  # type: ignore[attr-defined]
            query=text,
            limit=limit,
            offset=offset,
            scope=scope,
            library_branch_codes=library_branch_codes,
        )
        return page
