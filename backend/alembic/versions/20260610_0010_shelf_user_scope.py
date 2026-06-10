"""Shelf ownership becomes mandatory (identity Phase 2).

Completes the retrofit started in 20260610_0009: `shelf_entries.user_id`
flips to NOT NULL and the uniqueness rule becomes per-user —
`(user_id, source, source_book_id)` — so each reader can hold the same
Goodreads book on their own shelf.

The table is TRUNCATEd first (decided 2026-06-09: existing rows are
throwaway CSV imports; the owner re-imports through the user-scoped flow).
That makes the NOT NULL flip safe on any deployment state.

Revision ID: 20260610_0010
Revises: 20260610_0009
Create Date: 2026-06-10
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260610_0010"
down_revision: str | Sequence[str] | None = "20260610_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("TRUNCATE shelf_entries")
    op.alter_column(
        "shelf_entries", "user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False
    )
    op.drop_constraint("uq_shelf_entries_source_book", "shelf_entries", type_="unique")
    op.create_unique_constraint(
        "uq_shelf_entries_user_source_book",
        "shelf_entries",
        ["user_id", "source", "source_book_id"],
    )


def downgrade() -> None:
    op.execute("TRUNCATE shelf_entries")  # per-user rows can't collapse back losslessly
    op.drop_constraint("uq_shelf_entries_user_source_book", "shelf_entries", type_="unique")
    op.create_unique_constraint(
        "uq_shelf_entries_source_book", "shelf_entries", ["source", "source_book_id"]
    )
    op.alter_column(
        "shelf_entries", "user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True
    )
