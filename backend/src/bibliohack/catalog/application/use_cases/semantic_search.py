"""Semantic search use case — embed the query, then KNN over the catalogue.

The read API embeds the user's free-text query with the same BGE-M3 model used
to embed records (via the `Embedder` port), then asks the read repository for
the nearest neighbours by cosine distance. Keeping this in a use case (rather
than the router) means the embedding call + repo call are tested together with
fakes, and the HTTP layer stays a thin adapter.

The embedder is synchronous and makes a blocking HTTPS call to HuggingFace, so
we run it off the event loop with `asyncio.to_thread` — the read API serves
many requests concurrently and must not block on a network round-trip.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from bibliohack.catalog.domain.literary_profile import SearchScope

if TYPE_CHECKING:
    from bibliohack.catalog.application.dto import SearchPage
    from bibliohack.catalog.application.ports import Embedder


class SemanticSearch:
    """Embed a query and return its nearest catalogue neighbours."""

    def __init__(self, *, read_repo: object, embedder: Embedder) -> None:
        # `read_repo` is a CatalogReadRepository; typed loosely to avoid a
        # runtime import of the Protocol (it lives behind TYPE_CHECKING use).
        self._read_repo = read_repo
        self._embedder = embedder

    async def execute(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
        scope: SearchScope = SearchScope.LITERARY,
    ) -> SearchPage:
        from bibliohack.catalog.application.dto import SearchPage

        cleaned = query.strip()
        if not cleaned:
            return SearchPage(query=query, items=(), total=0, limit=limit, offset=offset)

        # Blocking HTTPS call to HF — keep it off the event loop.
        vector = await asyncio.to_thread(self._embedder.embed_query, cleaned)

        return await self._read_repo.semantic_search(  # type: ignore[attr-defined,no-any-return]
            query_vector=vector,
            query=query,
            limit=limit,
            offset=offset,
            scope=scope,
        )
