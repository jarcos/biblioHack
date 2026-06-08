"""Ports for the covers context (ARCHITECTURE.md §7.5.3).

The resolution use case depends only on these; concrete adapters
(OpenLibrary provider, Pillow processor, filesystem/MinIO store, Postgres
repo) live in `covers/infrastructure/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from bibliohack.covers.domain.cover import Cover, CoverSource


@dataclass(frozen=True, slots=True)
class FetchedImage:
    """Raw image bytes returned by a `CoverProvider`."""

    data: bytes
    source: CoverSource
    license: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    """A normalised cover ready to store: WebP bytes + its content address."""

    webp: bytes
    sha256: str
    width: int
    height: int


class CoverProvider(Protocol):
    """One source in the fallback chain (Open Library, Google Books, …)."""

    async def fetch(self, isbn: str) -> FetchedImage | None:
        """Return the cover bytes for `isbn`, or None when this source has none."""
        ...


class ImageProcessor(Protocol):
    """Decode arbitrary image bytes → a normalised WebP + sha256 + dimensions."""

    def process(self, raw: bytes) -> ProcessedImage: ...


class CoverStore(Protocol):
    """Content-addressed blob store for cover images (filesystem / MinIO)."""

    async def exists(self, sha256: str) -> bool: ...

    async def put(self, sha256: str, data: bytes) -> None:
        """Store `data` under its content address. Idempotent (immutable blobs)."""
        ...

    async def get(self, sha256: str) -> bytes | None:
        """Return the stored bytes for `sha256`, or None if absent."""
        ...


class CoverRepository(Protocol):
    """Persistence for `covers` metadata rows."""

    async def get_by_isbn(self, isbn: str) -> Cover | None: ...

    async def upsert(self, cover: Cover) -> None:
        """Insert or update the cover row for `cover.isbn_13`."""
        ...

    async def isbns_needing_cover(self, *, limit: int) -> list[str]:
        """ISBN-13s present in the catalog with no resolved/nofound cover yet."""
        ...
