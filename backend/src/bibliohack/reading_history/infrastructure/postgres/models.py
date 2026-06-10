"""SQLAlchemy model for the `shelf_entries` table (reading history / M4).

No `from __future__ import annotations` — SQLAlchemy 2.0 resolves Mapped[T] at
runtime (see catalog/infrastructure/postgres/models.py for the rationale).

One row per book the reader logged at an external source (Goodreads for now).
`matched_record_id` links to our catalogue when we could resolve the book;
it's nullable because most personal libraries contain editions the Andalusian
network doesn't hold. Identity is `(source, source_book_id)` so re-importing an
updated export upserts in place rather than duplicating.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from bibliohack.shared.infrastructure.db import Base


class ShelfEntryModel(Base):
    __tablename__ = "shelf_entries"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)

    # Owner. Nullable during the identity transition (Phase 0/1 of the
    # identity milestone): existing writes don't carry a user yet. Phase 2
    # truncates the table, flips this to NOT NULL, and swaps the uniqueness
    # constraint to (user_id, source, source_book_id).
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
    )

    # Provenance — where the entry came from and its native id there.
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="goodreads")
    source_book_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Raw bibliographic fields as the source recorded them (kept verbatim so a
    # title/author re-match can run later without re-importing).
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text)
    isbn_13: Mapped[str | None] = mapped_column(String(13))

    # Reader signal (the recommender's fuel): shelf, 1-5 rating (0/NULL = unrated),
    # review text, and the dates Goodreads tracked.
    shelf: Mapped[str] = mapped_column(String(20), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer)
    review: Mapped[str | None] = mapped_column(Text)
    date_read: Mapped[date | None] = mapped_column(Date)
    date_added: Mapped[date | None] = mapped_column(Date)

    # Catalogue link — NULL until/unless matched. ondelete SET NULL so pruning
    # a catalogue record doesn't delete the reader's shelf entry.
    matched_record_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bibliographic_records.id", ondelete="SET NULL"),
    )
    matched_via: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source", "source_book_id", name="uq_shelf_entries_source_book"),
        Index("ix_shelf_entries_isbn_13", "isbn_13"),
        Index("ix_shelf_entries_matched_record_id", "matched_record_id"),
        Index("ix_shelf_entries_shelf", "shelf"),
        Index("ix_shelf_entries_user_id", "user_id"),
    )
