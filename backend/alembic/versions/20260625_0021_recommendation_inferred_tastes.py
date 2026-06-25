"""Persist cold-start inferred tastes on the recommendations cache.

The LLM cold-start path (§8.3.3) infers short genre/topic "tastes" the UI shows
as «detectamos que te gusta…» chips. They were returned only on a fresh
generation and lost on a cache hit (kept migration-free at the time), so the
chips flickered away on reload. Persist them on the cached batch so the chips
are stable for the life of the batch.

`inferred_tastes` is a nullable text array, denormalised onto each row of a
batch (every row of one batch shares the same value). NULL for taste-centroid
batches, which carry no inferred chips.

Revision ID: 20260625_0021
Revises: 20260622_0020
Create Date: 2026-06-25
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260625_0021"
down_revision: str | Sequence[str] | None = "20260622_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column("inferred_tastes", postgresql.ARRAY(sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recommendations", "inferred_tastes")
