"""Read-side DTOs for the bookshelf.

`ShelfEntryView` is one logged book as the API renders it: the reader's own
fields (shelf, rating, date) plus — when the book was matched to the catalogue
— the same `CatalogRecordSummary` projection search uses, so the UI gets the
cover and live availability for free. The HTTP layer maps these onto Pydantic
schemas; the application stays Pydantic-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bibliohack.catalog.application.dto import CatalogRecordSummary


@dataclass(frozen=True, slots=True)
class ShelfEntryView:
    """One book on the shelf, optionally linked to a catalogue record."""

    source_book_id: str
    title: str
    author: str | None
    isbn_13: str | None
    shelf: str
    rating: int | None
    date_read: str | None  # ISO date string, or None
    matched_via: str
    # The catalogue projection (titn, cover, availability) when matched, else None.
    match: CatalogRecordSummary | None = None
