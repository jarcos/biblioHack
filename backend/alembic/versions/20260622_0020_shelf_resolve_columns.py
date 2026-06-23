"""Demand-driven shelf fetcher — resolve bookkeeping on `shelf_entries`.

The fetcher (kanban "Demand-driven fetcher (unmatched shelf books)", the
user-shelf sibling of canon C3) asks the live OPAC whether the RBPA holds a
still-unmatched shelf entry and, when it does, seeds the TITN for the worker.
These columns track that attempt so the crawl-plane job can pick eligible rows,
honour a re-try cooldown, and never re-query the same miss every tick:

- `resolve_status`   — 'unchecked' | 'held' | 'not_held' (mirrors canon's
  acquire_status; orthogonal to `matched_via`, which records *how* a link was
  made, not whether we asked the OPAC).
- `resolve_attempts` — how many times we've queried the OPAC for this entry.
- `last_resolved_at` — when we last queried (drives the cooldown).

The partial index supports the eligibility scan (unmatched rows, oldest attempt
first). A successful re-match sets `matched_record_id`, which drops the row out
of the partial index for free.

Revision ID: 20260622_0020
Revises: 20260622_0019
Create Date: 2026-06-22
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260622_0020"
down_revision: str | Sequence[str] | None = "20260622_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shelf_entries",
        sa.Column("resolve_status", sa.String(16), nullable=False, server_default="unchecked"),
    )
    op.add_column(
        "shelf_entries",
        sa.Column("resolve_attempts", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "shelf_entries",
        sa.Column("last_resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Eligibility scan: only unmatched entries are resolvable; order by the
    # last attempt (NULLS FIRST → never-tried first) is served by this index.
    op.create_index(
        "ix_shelf_entries_resolvable",
        "shelf_entries",
        ["last_resolved_at"],
        postgresql_where=sa.text("matched_record_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_shelf_entries_resolvable", table_name="shelf_entries")
    op.drop_column("shelf_entries", "last_resolved_at")
    op.drop_column("shelf_entries", "resolve_attempts")
    op.drop_column("shelf_entries", "resolve_status")
