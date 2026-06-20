"""Open Library ratings client — the canon popularity signal (C4).

Off-OPAC: hits ``openlibrary.org/search.json?isbn=…&fields=ratings_count``, which
returns a work's ratings count in a single request (no work→edition hops). The
count feeds ``canon_seed.ol_rating_count`` (a popularity signal that deepens
canon notability). Open Library is free/no-auth but expects a descriptive
``User-Agent`` and modest request rates.

The JSON→count mapping is a pure function (``parse_rating_count``) so it's
unit-testable without the network; the client only adds transport. A successful
lookup returns an ``int >= 0`` (0 = Open Library has no ratings for the ISBN); a
transport / non-200 error returns ``None`` so the caller can leave the row
unrated and retry later rather than recording a bogus 0.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

log = logging.getLogger(__name__)

_SEARCH_URL = "https://openlibrary.org/search.json"


def parse_rating_count(payload: Mapping[str, Any]) -> int:
    """Extract the ratings count from an OL search response (0 if absent)."""
    docs = payload.get("docs")
    if not isinstance(docs, list) or not docs:
        return 0
    first = docs[0]
    if not isinstance(first, dict):
        return 0
    raw = first.get("ratings_count")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


class OpenLibraryRatingsClient:
    """Fetch an Open Library ratings count by ISBN."""

    def __init__(self, *, user_agent: str, timeout_seconds: float = 15.0) -> None:
        self._user_agent = user_agent
        self._timeout = timeout_seconds

    async def fetch_rating_count(self, isbn: str) -> int | None:
        """Return the OL ratings count for `isbn` (0 if none), or None on error."""
        import httpx  # type: ignore[import-not-found,unused-ignore]

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                response = await client.get(
                    _SEARCH_URL,
                    params={"isbn": isbn, "fields": "ratings_count"},
                    headers={"User-Agent": self._user_agent},
                )
        except httpx.HTTPError as exc:
            log.warning("openlibrary.ratings.error isbn=%s error=%s", isbn, exc)
            return None

        if response.status_code != 200:
            log.warning("openlibrary.ratings.status isbn=%s status=%d", isbn, response.status_code)
            return None
        return parse_rating_count(response.json())
