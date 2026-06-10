"""Ports for the reading-history (bookshelf) context.

The import use case depends on these abstractions; the Postgres implementation
lives in `reading_history/infrastructure/postgres/`. Tests substitute in-memory
fakes. Identifiers cross the boundary as plain strings (UUIDs) so the
application layer never imports SQLAlchemy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date, datetime

    from bibliohack.reading_history.application.use_cases.import_shelf import ImportStats
    from bibliohack.reading_history.domain.import_job import ImportJobStatus
    from bibliohack.reading_history.domain.shelf import MatchVia, Shelf


@dataclass(frozen=True, slots=True)
class ShelfEntryData:
    """A shelf entry ready to persist — raw book fields plus the resolved match.

    `user_id` is the owning user (UUID string): shelves are per-user since
    the identity milestone.
    """

    user_id: str
    source: str
    source_book_id: str
    title: str
    author: str | None
    isbn_13: str | None
    shelf: Shelf
    rating: int | None
    review: str | None
    date_read: date | None
    date_added: date | None
    matched_record_id: str | None
    matched_via: MatchVia


class ShelfRepository(Protocol):
    """Persistence + catalogue matching for shelf entries.

    Matching reads the catalogue (`isbns`, `bibliographic_records`,
    `contributors`); persistence upserts into `shelf_entries`. They live on one
    port because the import use case needs both inside a single transaction and
    the only implementation is the same Postgres session.
    """

    async def match_isbn13(self, isbn13: str) -> str | None:
        """Return the catalogue record id whose ISBN-13 equals `isbn13`, or None."""
        ...

    async def match_title_author(self, title: str, author: str | None) -> str | None:
        """Best catalogue record id by title (+author) trigram similarity, or None.

        Uses pg_trgm similarity above a conservative threshold so only confident
        matches link; ambiguous books stay unmatched (re-checkable later).
        """
        ...

    async def upsert_entry(self, entry: ShelfEntryData) -> bool:
        """Insert or update a shelf entry by (user_id, source, source_book_id).

        Returns True when a new row was inserted, False when an existing row was
        updated — lets the import report new-vs-updated.
        """
        ...


@dataclass(frozen=True, slots=True)
class ClaimedImportJob:
    """What the worker needs to run a claimed job."""

    user_id: str
    csv_content: str


@dataclass(frozen=True, slots=True)
class ImportJobView:
    """Read projection of a job for the polling endpoint."""

    id: str
    status: ImportJobStatus
    filename: str | None
    total: int | None
    inserted: int | None
    updated: int | None
    matched_isbn: int | None
    matched_title_author: int | None
    unmatched: int | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class ImportJobRepository(Protocol):
    """Persistence + state machine for background shelf imports."""

    async def create(self, *, user_id: str, filename: str | None, csv_content: str) -> str:
        """Insert a queued job; returns its id."""
        ...

    async def claim(self, job_id: str) -> ClaimedImportJob | None:
        """Atomically flip queued → running; None if missing or already taken."""
        ...

    async def mark_done(self, job_id: str, stats: ImportStats) -> None: ...

    async def mark_failed(self, job_id: str, error: str) -> None: ...

    async def get_view(self, job_id: str, *, user_id: str) -> ImportJobView | None:
        """The job as seen by its owner — other users' jobs are invisible."""
        ...


class ImportJobQueue(Protocol):
    """Hands a created job to the background worker (Dramatiq in production)."""

    def enqueue(self, job_id: str) -> None: ...
