"""Covers metadata table (§7.5).

Adds `covers` — per-ISBN cover-resolution metadata. The image bytes live in
the content-addressed CoverStore (filesystem now, MinIO later), not here;
this row records status, source, license, dimensions and the sha256 content
address. Keyed by ISBN-13 (one cover per ISBN).

Revision ID: 20260603_0004
Revises: 20260601_0003
Create Date: 2026-06-03
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260603_0004"
down_revision: str | Sequence[str] | None = "20260601_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "covers",
        sa.Column("isbn_13", sa.String(length=13), primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_covers_status", "covers", ["status"])


def downgrade() -> None:
    op.drop_index("ix_covers_status", table_name="covers")
    op.drop_table("covers")
