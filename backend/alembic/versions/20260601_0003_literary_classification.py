"""Literary classification — audience + literary_form + raw CDU on records.

Adds the columns that back the default "literary" search/recommender scope
(see catalog/domain/literary_profile.py):

1. `classification` — the raw UDC/CDU string (MARC T080). Parsed since M1
   but previously dropped at ingest; persisted now so the classifier and
   future genre faceting can re-read it without a re-crawl.
2. `audience`       — adult / youth / children / unknown.
3. `literary_form`  — literary / nonfiction / unknown.

Both `audience` and `literary_form` are NOT NULL with a server_default of
'unknown'. That default backfills any pre-existing rows, and 'unknown' sits
*inside* the default scope, so nothing already ingested disappears from
search. Existing rows keep 'unknown' until a re-crawl recomputes a real
value — fine, since the production mirror is still empty at this point.

A composite btree index on (audience, literary_form) supports the scope
predicate applied after the FTS GIN match.

Revision ID: 20260601_0003
Revises: 20260529_0002
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260601_0003"
down_revision: str | Sequence[str] | None = "20260529_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bibliographic_records",
        sa.Column("classification", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "bibliographic_records",
        sa.Column(
            "audience",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "bibliographic_records",
        sa.Column(
            "literary_form",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.create_index(
        "ix_bibliographic_records_scope",
        "bibliographic_records",
        ["audience", "literary_form"],
    )


def downgrade() -> None:
    op.drop_index("ix_bibliographic_records_scope", table_name="bibliographic_records")
    op.drop_column("bibliographic_records", "literary_form")
    op.drop_column("bibliographic_records", "audience")
    op.drop_column("bibliographic_records", "classification")
