"""Pydantic response schemas for the bookshelf API."""

from __future__ import annotations

from pydantic import BaseModel, Field

# Runtime import (not TYPE_CHECKING): Pydantic resolves this annotation at
# model-build time to construct the nested `match` field.
from bibliohack.catalog.interfaces.http.schemas import CatalogRecordSummarySchema  # noqa: TC001


class ShelfEntrySchema(BaseModel):
    """One logged book, with its catalogue match when resolved."""

    source_book_id: str
    title: str
    author: str | None = None
    isbn_13: str | None = None
    rating: int | None = Field(None, ge=1, le=5, description="Reader rating 1-5, null if unrated.")
    date_read: str | None = Field(None, description="ISO date the reader finished it, if known.")
    matched_via: str = Field("none", description="isbn | title_author | none.")
    match: CatalogRecordSummarySchema | None = Field(
        None, description="Catalogue projection (titn, cover, availability) when matched."
    )


class ShelfCountsSchema(BaseModel):
    """Summary tallies for the shelf header."""

    total: int = Field(..., ge=0)
    matched: int = Field(..., ge=0, description="Books linked to a catalogue record.")
    read: int = Field(..., ge=0)
    currently_reading: int = Field(..., ge=0)
    to_read: int = Field(..., ge=0)


class ShelfResponseSchema(BaseModel):
    """The whole bookshelf, grouped by shelf."""

    counts: ShelfCountsSchema
    read: list[ShelfEntrySchema] = Field(default_factory=list)
    currently_reading: list[ShelfEntrySchema] = Field(default_factory=list)
    to_read: list[ShelfEntrySchema] = Field(default_factory=list)
