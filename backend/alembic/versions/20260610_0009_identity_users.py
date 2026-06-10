"""Identity context — users, one-time tokens, shelf ownership (Phase 0).

Creates the `users` table (CITEXT email, Argon2id password hash) plus the
`email_verification_tokens` / `password_reset_tokens` companion tables
(SHA-256 token hashes, single-use, expiring), and adds a *nullable*
`user_id` FK to `shelf_entries`.

Deviation from the milestone plan, on purpose: the plan's Phase 0 truncated
`shelf_entries` and added `user_id NOT NULL` immediately. But shelf writes
only learn to carry a user in Phase 2 — NOT NULL now would break the
existing single-user import path and its integration tests, violating the
"every step independently shippable on a green gate" rule. So Phase 0 adds
the column nullable; Phase 2 truncates, flips to NOT NULL, and swaps the
unique constraint to (user_id, source, source_book_id). Existing rows are
throwaway CSV imports (decided 2026-06-09), so nothing is backfilled.

Revision ID: 20260610_0009
Revises: 20260608_0008
Create Date: 2026-06-10
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260610_0009"
down_revision: str | Sequence[str] | None = "20260608_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _token_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(f"ix_{name}_user_id", name, ["user_id"])


def upgrade() -> None:
    # Case-insensitive email uniqueness at the DB level, managed like the
    # other extensions (pg_trgm, spanish_unaccent): created here defensively.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    _token_table("email_verification_tokens")
    _token_table("password_reset_tokens")

    # Shelf ownership — nullable for now (see module docstring).
    op.add_column(
        "shelf_entries",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_shelf_entries_user",
        "shelf_entries",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_shelf_entries_user_id", "shelf_entries", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_shelf_entries_user_id", table_name="shelf_entries")
    op.drop_constraint("fk_shelf_entries_user", "shelf_entries", type_="foreignkey")
    op.drop_column("shelf_entries", "user_id")
    for name in ("password_reset_tokens", "email_verification_tokens"):
        op.drop_index(f"ix_{name}_user_id", table_name=name)
        op.drop_table(name)
    op.drop_table("users")
