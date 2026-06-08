"""Google Books cover provider — fallback when Open Library has nothing.

Two requests: the volumes lookup (`?q=isbn:…`) yields a thumbnail URL, which
we then fetch. We store the bytes like any other source (single self-hosted
mirror) and record `license="googlebooks"` for provenance / takedown. Placed
after Open Library in the chain, so it only runs when OL has no image.
"""

from __future__ import annotations

from bibliohack.covers.application.ports import FetchedImage
from bibliohack.covers.domain.cover import CoverSource

_VOLUMES_URL = "https://www.googleapis.com/books/v1/volumes"


class GoogleBooksCoverProvider:
    """Fetch a cover by ISBN from the Google Books API (fallback source)."""

    def __init__(self, *, user_agent: str, timeout_seconds: float = 15.0) -> None:
        self._user_agent = user_agent
        self._timeout = timeout_seconds

    async def fetch(self, isbn: str) -> FetchedImage | None:
        # Lazy import — httpx lives in the [covers] extra, off the core/API path.
        import httpx  # type: ignore[import-not-found,unused-ignore]

        headers = {"User-Agent": self._user_agent}
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            lookup = await client.get(
                _VOLUMES_URL,
                params={"q": f"isbn:{isbn}", "country": "ES", "maxResults": "1"},
                headers=headers,
            )
            if lookup.status_code != 200:
                return None
            image_url = thumbnail_url(lookup.json())
            if image_url is None:
                return None
            image = await client.get(image_url, headers=headers)
        if image.status_code == 200 and image.content:
            return FetchedImage(
                data=bytes(image.content),
                source=CoverSource.GOOGLEBOOKS,
                license="googlebooks",
            )
        return None


def thumbnail_url(payload: object) -> str | None:
    """Pull the best thumbnail URL out of a Google Books volumes response.

    Returns None when the payload has no usable image. Forces https and drops
    the page-curl effect Google adds by default.
    """
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    info = items[0].get("volumeInfo")
    links = info.get("imageLinks") if isinstance(info, dict) else None
    if not isinstance(links, dict):
        return None
    for key in ("thumbnail", "smallThumbnail"):
        url = links.get(key)
        if isinstance(url, str) and url:
            return url.replace("http://", "https://").replace("&edge=curl", "")
    return None
