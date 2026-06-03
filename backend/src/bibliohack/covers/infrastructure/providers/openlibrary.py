"""Open Library Covers provider — the storable primary source (§7.5.2)."""

from __future__ import annotations

from bibliohack.covers.application.ports import FetchedImage
from bibliohack.covers.domain.cover import CoverSource

_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"


class OpenLibraryCoverProvider:
    """Fetch a cover by ISBN from Open Library.

    `default=false` makes the API return 404 when it has no image (instead of
    a blank 1x1 placeholder), so the caller can record NOFOUND cleanly. The
    image is permissively licensed — safe to store and redistribute (§7.5.2).
    """

    def __init__(self, *, user_agent: str, timeout_seconds: float = 15.0) -> None:
        self._user_agent = user_agent
        self._timeout = timeout_seconds

    async def fetch(self, isbn: str) -> FetchedImage | None:
        # Lazy import — httpx lives in the [covers] extra, off the core/API path.
        import httpx  # type: ignore[import-not-found,unused-ignore]

        url = _URL.format(isbn=isbn)
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.get(
                url,
                params={"default": "false"},
                headers={"User-Agent": self._user_agent},
            )
        if response.status_code == 200 and response.content:
            return FetchedImage(
                data=bytes(response.content),
                source=CoverSource.OPENLIBRARY,
                license="openlibrary",
            )
        return None
