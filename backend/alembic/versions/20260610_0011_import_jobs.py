"""Background shelf imports — the `import_jobs` table (identity Phase 2B).

One row per uploaded Goodreads CSV: the raw CSV travels in the row (small,
capped uploads — no shared filesystem or object store needed between the api
and the worker), the Dramatiq worker claims it (queued → running) and writes
back stats (done) or an error (failed). The frontend polls
`GET /api/shelf/import/{id}`.

Revision ID: 20260610_0011
Revises: 20260610_0010
Create Date: 2026-06-10
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260610_0011"
down_revision: str | Sequence[str] | None = "20260610_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("csv_content", sa.Text(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column("inserted", sa.Integer(), nullable=True),
        sa.Column("updated", sa.Integer(), nullable=True),
        sa.Column("matched_isbn", sa.Integer(), nullable=True),
        sa.Column("matched_title_author", sa.Integer(), nullable=True),
        sa.Column("unmatched", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_import_jobs_user_id", "import_jobs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_import_jobs_user_id", table_name="import_jobs")
    op.drop_table("import_jobs")
