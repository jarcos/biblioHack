"""FastAPI router for the bookshelf (reading history).

- GET /shelf — the reader's logged books, grouped by shelf, each enriched with
  its catalogue match (cover + availability) when one was found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends

# AsyncSession is a runtime import for the same FastAPI type-hint introspection
# reason as the catalog router.
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from bibliohack.catalog.interfaces.http.schemas import CatalogRecordSummarySchema, CoverSchema
from bibliohack.interfaces.http.dependencies import get_session
from bibliohack.reading_history.domain.shelf import Shelf
from bibliohack.reading_history.infrastructure.postgres.shelf_read_repository import (
    PostgresShelfReadRepository,
)
from bibliohack.reading_history.interfaces.http.schemas import (
    ShelfCountsSchema,
    ShelfEntrySchema,
    ShelfResponseSchema,
)

if TYPE_CHECKING:
    from bibliohack.catalog.application.dto import CatalogRecordSummary
    from bibliohack.reading_history.application.dto import ShelfEntryView

# Served under /api/* — the prefix the Cloudflare tunnel routes to this API
# (a bare /shelf would collide with the frontend's /shelf page route and hit
# the static frontend instead). The catalog routes predate this and use their
# own /catalog/* tunnel rule.
router = APIRouter(prefix="/api/shelf", tags=["shelf"])


@router.get("", response_model=ShelfResponseSchema)
async def get_shelf(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ShelfResponseSchema:
    """Return the whole bookshelf grouped by shelf, with per-book catalogue matches.

    Single-user: there is one reader, so no auth or user scoping. Unmatched
    books still appear (they carry their raw title/author/ISBN); matched books
    additionally expose the catalogue cover and live availability.
    """
    entries = await PostgresShelfReadRepository(session).list_entries()

    buckets: dict[str, list[ShelfEntrySchema]] = {
        Shelf.READ.value: [],
        Shelf.CURRENTLY_READING.value: [],
        Shelf.TO_READ.value: [],
    }
    matched = 0
    for entry in entries:
        if entry.match is not None:
            matched += 1
        buckets.setdefault(entry.shelf, []).append(_entry_to_schema(entry))

    read = buckets[Shelf.READ.value]
    currently_reading = buckets[Shelf.CURRENTLY_READING.value]
    to_read = buckets[Shelf.TO_READ.value]

    return ShelfResponseSchema(
        counts=ShelfCountsSchema(
            total=len(entries),
            matched=matched,
            read=len(read),
            currently_reading=len(currently_reading),
            to_read=len(to_read),
        ),
        read=read,
        currently_reading=currently_reading,
        to_read=to_read,
    )


# ─── helpers ─────────────────────────────────────────────────


def _entry_to_schema(entry: ShelfEntryView) -> ShelfEntrySchema:
    return ShelfEntrySchema(
        source_book_id=entry.source_book_id,
        title=entry.title,
        author=entry.author,
        isbn_13=entry.isbn_13,
        rating=entry.rating,
        date_read=entry.date_read,
        matched_via=entry.matched_via,
        match=_summary_to_schema(entry.match) if entry.match is not None else None,
    )


def _summary_to_schema(summary: CatalogRecordSummary) -> CatalogRecordSummarySchema:
    cover = (
        CoverSchema(status=summary.cover.status, source=summary.cover.source, url=summary.cover.url)
        if summary.cover is not None
        else None
    )
    return CatalogRecordSummarySchema(
        titn=summary.titn,
        title=summary.title,
        authors=list(summary.authors),
        publisher=summary.publisher,
        pub_year=summary.pub_year,
        copies_count=summary.copies_count,
        audience=summary.audience,
        literary_form=summary.literary_form,
        available_count=summary.available_count,
        cover=cover,
    )
