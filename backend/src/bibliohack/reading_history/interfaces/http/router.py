"""FastAPI router for the bookshelf (reading history).

- GET  /api/shelf — the caller's logged books, grouped by shelf, enriched with
  catalogue matches (cover + availability) where found.
- POST /api/shelf/import — upload a Goodreads CSV; validated inline, matched
  in the Dramatiq worker. Returns 202 + a job id.
- GET  /api/shelf/import/{job_id} — poll a job's status/stats.
"""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

# AsyncSession is a runtime import for the same FastAPI type-hint introspection
# reason as the catalog router.
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from bibliohack.catalog.interfaces.http.schemas import CatalogRecordSummarySchema, CoverSchema

# Runtime import — FastAPI evaluates endpoint signatures at runtime (see the
# note in identity/interfaces/http/dependencies.py).
from bibliohack.identity.domain.user import User  # noqa: TC001
from bibliohack.identity.interfaces.http.dependencies import get_current_user
from bibliohack.interfaces.http.dependencies import get_session, rate_limit
from bibliohack.reading_history.application.ports import (  # noqa: TC001
    ImportJobQueue,
    ImportJobRepository,
)
from bibliohack.reading_history.domain.shelf import Shelf
from bibliohack.reading_history.infrastructure.goodreads.csv_parser import parse_goodreads_csv
from bibliohack.reading_history.infrastructure.postgres.shelf_read_repository import (
    PostgresShelfReadRepository,
)
from bibliohack.reading_history.interfaces.http.dependencies import (
    get_import_job_queue,
    get_import_job_repository,
)
from bibliohack.reading_history.interfaces.http.schemas import (
    ImportJobSchema,
    ShelfCountsSchema,
    ShelfEntrySchema,
    ShelfResponseSchema,
)
from bibliohack.shared.infrastructure.settings import Settings, get_settings

if TYPE_CHECKING:
    from bibliohack.catalog.application.dto import CatalogRecordSummary
    from bibliohack.reading_history.application.dto import ShelfEntryView
    from bibliohack.reading_history.application.ports import ImportJobView

# Served under /api/* — the prefix the Cloudflare tunnel routes to this API
# (a bare /shelf would collide with the frontend's /shelf page route and hit
# the static frontend instead). The catalog routes predate this and use their
# own /catalog/* tunnel rule.
router = APIRouter(prefix="/api/shelf", tags=["shelf"])

# Imports are heavy (per-row trigram matching on the worker); cap how often
# one caller can queue them. Module-level so tests can override it.
import_rate_limit = rate_limit("shelf-import", limit=10, window_seconds=3600)


@router.get("", response_model=ShelfResponseSchema)
async def get_shelf(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> ShelfResponseSchema:
    """Return the authenticated user's bookshelf, grouped, with catalogue matches.

    Unmatched books still appear (they carry their raw title/author/ISBN);
    matched books additionally expose the catalogue cover and live
    availability.
    """
    entries = await PostgresShelfReadRepository(session).list_entries(str(user.id))

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


@router.post(
    "/import",
    response_model=ImportJobSchema,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(import_rate_limit)],
)
async def import_shelf_csv(
    file: UploadFile,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    jobs: Annotated[ImportJobRepository, Depends(get_import_job_repository)],
    queue: Annotated[ImportJobQueue, Depends(get_import_job_queue)],
) -> ImportJobSchema:
    """Accept a Goodreads export CSV and queue it for background matching.

    Validation (size cap, decodability, row cap, at least one book) runs
    inline so junk never reaches the worker; the per-row catalogue matching —
    the expensive part — runs in the Dramatiq worker. Poll the returned job.
    """
    raw = await file.read(settings.import_max_upload_bytes + 1)
    if len(raw) > settings.import_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="csv exceeds the upload size limit",
        )
    try:
        csv_text = raw.decode("utf-8-sig")  # Goodreads exports may carry a BOM
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="file is not UTF-8 text",
        ) from exc

    try:
        rows = parse_goodreads_csv(io.StringIO(csv_text))
    except csv.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="not a parseable CSV file",
        ) from exc
    if not rows:
        # Covers structurally-valid CSVs that aren't a Goodreads export too:
        # without Title/Book Id columns every row is skipped.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="no importable books found — is this a Goodreads library export?",
        )
    if len(rows) > settings.import_max_rows:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="too many rows for one import",
        )

    job_id = await jobs.create(user_id=str(user.id), filename=file.filename, csv_content=csv_text)
    queue.enqueue(job_id)

    view = await jobs.get_view(job_id, user_id=str(user.id))
    assert view is not None  # we just created it in this transaction
    return _job_to_schema(view)


@router.get("/import/{job_id}", response_model=ImportJobSchema)
async def get_import_job(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    jobs: Annotated[ImportJobRepository, Depends(get_import_job_repository)],
) -> ImportJobSchema:
    """Status of one of the caller's import jobs — others' jobs are a 404."""
    view = await jobs.get_view(job_id, user_id=str(user.id))
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such import")
    return _job_to_schema(view)


# ─── helpers ─────────────────────────────────────────────────


def _job_to_schema(view: ImportJobView) -> ImportJobSchema:
    return ImportJobSchema(
        id=view.id,
        status=view.status.value,
        filename=view.filename,
        total=view.total,
        inserted=view.inserted,
        updated=view.updated,
        matched_isbn=view.matched_isbn,
        matched_title_author=view.matched_title_author,
        unmatched=view.unmatched,
        error=view.error,
        created_at=view.created_at,
        finished_at=view.finished_at,
    )


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
