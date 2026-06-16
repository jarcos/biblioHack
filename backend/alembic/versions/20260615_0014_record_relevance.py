"""Catalogue relevance score on bibliographic records (Phase R0).

Adds the precomputable, intrinsic relevance signal that lets `/browse` and
search lead with the best titles instead of "newest TITN first":

- `relevance_score`     — the blended [0,1] score; indexed desc for ranking.
- `relevance_components`— per-component sub-scores (demand / holdings / recency
  / completeness), kept for debugging and a future "why this" UI badge set.
- `relevance_updated_at`— staleness tracking for the nightly recompute job.

The score itself is computed off the OPAC path by the recompute use case
(`bibliohack catalog relevance recompute`, scheduled on the crawler plane);
this migration only lands the columns + ranking index. Existing rows keep the
`server_default` of 0 until the first recompute runs — they simply rank last on
the new sort until then, never breaking `/browse`.

Revision ID: 20260615_0014
Revises: 20260611_0013
Create Date: 2026-06-15
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260615_0014"
down_revision: str | Sequence[str] | None = "20260611_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bibliographic_records",
        sa.Column(
            "relevance_score",
            sa.Double(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "bibliographic_records",
        sa.Column("relevance_components", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "bibliographic_records",
        sa.Column("relevance_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Ranking index: `/browse` default sort is relevance DESC. Name pinned so
    # the model's Index() matches what's on disk (autogenerate stays quiet).
    op.create_index(
        "ix_records_relevance",
        "bibliographic_records",
        [sa.text("relevance_score DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_records_relevance", table_name="bibliographic_records")
    op.drop_column("bibliographic_records", "relevance_updated_at")
    op.drop_column("bibliographic_records", "relevance_components")
    op.drop_column("bibliographic_records", "relevance_score")
