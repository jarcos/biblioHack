"""Recommendations — per-user cached suggestions (identity Phase 4 / M5).

One row per recommended catalogue record per user. `cache_key` is a
fingerprint of the user's shelf at generation time: when the shelf changes
the key changes, the cached rows stop matching, and the next request
regenerates. (The plan's in-process invalidation events don't survive our
multi-process reality — imports happen in the Dramatiq worker — so the
fingerprint does the invalidating instead.)

Revision ID: 20260610_0012
Revises: 20260610_0011
Create Date: 2026-06-10
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260610_0012"
down_revision: str | Sequence[str] | None = "20260610_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matched_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "matched_record_id", name="uq_recommendations_user_record"),
    )
    op.create_index("ix_recommendations_user_id", "recommendations", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_recommendations_user_id", table_name="recommendations")
    op.drop_table("recommendations")
