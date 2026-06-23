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
    from collections.abc import Sequence
    from datetime import date, datetime

    from bibliohack.reading_history.application.use_cases.import_shelf import ImportStats
    from bibliohack.reading_history.domain.import_job import ImportJobStatus
    from bibliohack.reading_history.domain.shelf import MatchVia, Shelf, ShelfResolveStatus


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


@dataclass(frozen=True, slots=True)
class UnmatchedShelfEntry:
    """An unmatched shelf entry, with just the fields a re-match needs.

    `id` is the `shelf_entries` row id (UUID string) so a successful match can be
    linked back to exactly this row.
    """

    id: str
    title: str
    author: str | None
    isbn_13: str | None


@dataclass(frozen=True, slots=True)
class ResolvableShelfBook:
    """A distinct unmatched book to resolve against the OPAC (demand-driven fetcher).

    Deduped across users: `entry_ids` are every still-unmatched shelf entry that
    shares this book (same ISBN-13, else same normalised title+author), so a single
    OPAC query — and its outcome — covers them all. `isbn13` are the distinct
    non-null ISBNs seen in the group (ISBN resolve tries each); `title`/`author` are
    a representative for the title+author fallback.
    """

    entry_ids: tuple[str, ...]
    title: str
    author: str | None
    isbn13: tuple[str, ...]


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

    async def iter_unmatched(self, *, limit: int) -> list[UnmatchedShelfEntry]:
        """Up to `limit` still-unmatched shelf entries (`matched_record_id IS NULL`).

        Oldest-attempt-first (never-tried entries lead) so a bounded re-match run
        makes steady progress through the backlog rather than re-scanning the same
        head each time.
        """
        ...

    async def link_match(self, entry_id: str, record_id: str, via: MatchVia) -> None:
        """Link an unmatched entry to a now-present catalogue record.

        Sets `matched_record_id` + `matched_via`; the row then drops out of
        `iter_unmatched`. Idempotent — re-linking the same pair is a no-op.
        """
        ...

    async def iter_resolvable_books(
        self, *, limit: int, cooldown_days: int
    ) -> list[ResolvableShelfBook]:
        """Up to `limit` distinct unmatched books eligible for an OPAC resolve.

        Eligible = still unmatched and either never asked (`unchecked`) or asked
        and not held but past the `cooldown_days` re-try window. Deduped across
        users by ISBN-13 (else normalised title+author) so each distinct book is
        queried once, oldest-attempt-first (never-tried books lead).
        """
        ...

    async def mark_resolve_result(
        self, entry_ids: Sequence[str], status: ShelfResolveStatus
    ) -> None:
        """Record an OPAC resolve outcome on every entry in a deduped book group.

        Sets `resolve_status`, bumps `resolve_attempts`, and stamps
        `last_resolved_at` so the cooldown applies. A `held`/`not_held` row then
        drops out of `iter_resolvable_books` (held permanently; not_held until the
        cooldown lapses).
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
