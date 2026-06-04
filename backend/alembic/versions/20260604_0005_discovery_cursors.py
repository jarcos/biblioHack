"""Discovery cursors — resumable expert-query pagination.

Adds `discovery_cursors`: one row per expert-query expression recording how
far we've paginated through its results list. Lets the nightly/hourly
`discover` advance through the full result set (e.g. ~55k records for
`@fepu>=2024`) across runs instead of re-scanning the first page every time.

Revision ID: 20260604_0005
Revises: 20260603_0004
Create Date: 2026-06-04
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260604_0005"
down_revision: str | Sequence[str] | None = "20260603_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_cursors",
        # The raw expert-query expression, e.g. '(@fepu>=2024)'.
        sa.Column("expression", sa.Text(), primary_key=True),
        # Number of results already covered = the DOC offset to resume at.
        sa.Column("next_offset", sa.Integer(), nullable=False, server_default="0"),
        # Total results the OPAC reported for this query at the last run.
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("discovery_cursors")
