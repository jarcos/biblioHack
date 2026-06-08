"""Reading-history shelf entries (Goodreads import / M4).

Creates `shelf_entries`: one row per book the reader logged at an external
source (Goodreads for now), optionally matched to a catalogue record by
ISBN-13 or a title/author trigram fallback. Identity is (source,
source_book_id) so re-importing an updated export upserts in place. The
matcher relies on pg_trgm `similarity()`, enabled here defensively (it is
already present for the contributor-name index).

Revision ID: 20260608_0008
Revises: 20260608_0007
Create Date: 2026-06-08
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260608_0008"
down_revision: str | Sequence[str] | None = "20260608_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "shelf_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="goodreads"),
        sa.Column("source_book_id", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("isbn_13", sa.String(13), nullable=True),
        sa.Column("shelf", sa.String(20), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("review", sa.Text(), nullable=True),
        sa.Column("date_read", sa.Date(), nullable=True),
        sa.Column("date_added", sa.Date(), nullable=True),
        sa.Column(
            "matched_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bibliographic_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("matched_via", sa.String(16), nullable=False, server_default="none"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("source", "source_book_id", name="uq_shelf_entries_source_book"),
    )
    op.create_index("ix_shelf_entries_isbn_13", "shelf_entries", ["isbn_13"])
    op.create_index("ix_shelf_entries_matched_record_id", "shelf_entries", ["matched_record_id"])
    op.create_index("ix_shelf_entries_shelf", "shelf_entries", ["shelf"])


def downgrade() -> None:
    op.drop_index("ix_shelf_entries_shelf", table_name="shelf_entries")
    op.drop_index("ix_shelf_entries_matched_record_id", table_name="shelf_entries")
    op.drop_index("ix_shelf_entries_isbn_13", table_name="shelf_entries")
    op.drop_table("shelf_entries")
