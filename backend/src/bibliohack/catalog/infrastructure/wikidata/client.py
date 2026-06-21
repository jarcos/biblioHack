"""WDQS HTTP client — a polite, resumable :class:`CanonSeedSource`.

Off-OPAC entirely: this hits ``query.wikidata.org/sparql``, which is free and
needs no auth but enforces a ~60s per-query timeout and rate-limits abusive
clients (429 + ``Retry-After``). So the client:

* paginates by **keyset** (page text built in ``query.py``): each page seeks
  past the last work IRI of the previous one, so deep pages stay cheap and don't
  504-timeout the way a growing ``OFFSET`` did. Stops when a short page signals
  the end of the result set;
* sends a descriptive ``User-Agent`` (WDQS etiquette / a 403 otherwise);
* backs off on 429 (honouring ``Retry-After``) and transient 5xx, with a
  bounded number of retries per page;
* paces successive pages so a long refresh stays a good citizen.

It yields domain :class:`CanonSeedWork` objects; the use case batches and
upserts them. No DB, no OPAC budget — safe to run monthly on the crawl plane.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from bibliohack.catalog.infrastructure.wikidata.query import (
    DEFAULT_MIN_SITELINKS,
    DEFAULT_PAGE_SIZE,
    build_canon_query,
    next_cursor,
    parse_bindings,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bibliohack.catalog.domain.canon import CanonSeedWork

log = logging.getLogger(__name__)

_ENDPOINT = "https://query.wikidata.org/sparql"
_MAX_RETRIES = 4
_BASE_BACKOFF_SECONDS = 2.0
_MAX_BACKOFF_SECONDS = 60.0


class WikidataCanonSource:
    """Fetch canonical literary works from Wikidata, page by page."""

    def __init__(
        self,
        *,
        user_agent: str,
        min_sitelinks: int = DEFAULT_MIN_SITELINKS,
        spanish_only: bool = False,
        page_size: int = DEFAULT_PAGE_SIZE,
        page_pause_seconds: float = 1.0,
        timeout_seconds: float = 75.0,
        endpoint: str = _ENDPOINT,
    ) -> None:
        self._user_agent = user_agent
        self._min_sitelinks = min_sitelinks
        self._spanish_only = spanish_only
        self._page_size = page_size
        self._page_pause = page_pause_seconds
        self._timeout = timeout_seconds
        self._endpoint = endpoint

    async def fetch_works(self, *, max_works: int | None = None) -> AsyncIterator[CanonSeedWork]:
        """Yield seed works across as many pages as needed (or until ``max_works``).

        Pages are fetched by keyset seek: each page asks for works sorting after
        the previous page's last work IRI. A page shorter than ``page_size``
        means we've reached the end of the result set, so iteration stops there.
        """
        import httpx  # type: ignore[import-not-found,unused-ignore]

        emitted = 0
        after_qid: str | None = None
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            while True:
                query = build_canon_query(
                    min_sitelinks=self._min_sitelinks,
                    spanish_only=self._spanish_only,
                    limit=self._page_size,
                    after_qid=after_qid,
                )
                rows = await self._fetch_page(client, query)
                if not rows:
                    return
                for work in parse_bindings(rows):
                    yield work
                    emitted += 1
                    if max_works is not None and emitted >= max_works:
                        return
                if len(rows) < self._page_size:
                    return  # last (partial) page
                cursor = next_cursor(rows)
                if cursor is None or cursor == after_qid:
                    # No usable cursor (or it didn't advance) — stop rather than
                    # risk re-requesting the same page forever.
                    return
                after_qid = cursor
                await asyncio.sleep(self._page_pause)

    async def _fetch_page(self, client: object, query: str) -> list[dict[str, Any]]:
        """One page with bounded retry/backoff. Returns the raw bindings list."""
        import httpx  # type: ignore[import-not-found,unused-ignore]

        assert isinstance(client, httpx.AsyncClient)
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await client.get(
                    self._endpoint,
                    params={"query": query, "format": "json"},
                    headers={
                        "User-Agent": self._user_agent,
                        "Accept": "application/sparql-results+json",
                    },
                )
            except httpx.HTTPError as exc:  # transport-level (timeout, conn reset)
                last_exc = exc
                await asyncio.sleep(self._backoff(attempt))
                continue

            if response.status_code == 200:
                payload = response.json()
                bindings = payload.get("results", {}).get("bindings", [])
                return list(bindings)
            if response.status_code == 429 or response.status_code >= 500:
                delay = self._retry_after(response) or self._backoff(attempt)
                log.warning(
                    "WDQS %s — backing off %.1fs (attempt %d/%d)",
                    response.status_code,
                    delay,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                await asyncio.sleep(delay)
                continue
            # 4xx other than 429 won't fix itself — fail loudly.
            response.raise_for_status()

        msg = f"WDQS page failed after {_MAX_RETRIES} attempts"
        raise RuntimeError(msg) from last_exc

    @staticmethod
    def _backoff(attempt: int) -> float:
        return float(min(_BASE_BACKOFF_SECONDS * (2**attempt), _MAX_BACKOFF_SECONDS))

    @staticmethod
    def _retry_after(response: object) -> float | None:
        import httpx  # type: ignore[import-not-found,unused-ignore]

        assert isinstance(response, httpx.Response)
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return min(float(raw), _MAX_BACKOFF_SECONDS)
        except ValueError:
            return None
