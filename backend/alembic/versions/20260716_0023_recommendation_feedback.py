"""The recommendation feedback signal store (chat-recs P1, §D4).

Adds `recommendation_feedback`: an append-only log of the reader's return
channel — one row per like/dislike/«más como esto»/«no me interesa» on a
recommended record. The *latest* signal per (user, record) re-weights the taste
centroid (§4) and joins the recommendations cache key so a button press
regenerates the batch on the next request (§D4).

`signal` is a plain `varchar(20)` (see `FeedbackSignal`), matching the
enum-ish-column convention used by `shelf_entries.shelf` / `resolve_status` —
no native Postgres enum, so P2's `read_rating` writer needs no migration.
`rating` is set only for that future `read_rating` signal.

Revision ID: 20260716_0023
Revises: 20260626_0022
Create Date: 2026-07-16
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260716_0023"
down_revision: str | Sequence[str] | None = "20260626_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendation_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal", sa.String(length=20), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            # clock_timestamp() (not now()): the "latest signal per record"
            # ordering must reflect insertion order even for two signals written
            # in the same transaction, where now() would tie at transaction start.
            server_default=sa.func.clock_timestamp(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["record_id"], ["bibliographic_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recommendation_feedback_user_record_created",
        "recommendation_feedback",
        ["user_id", "record_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recommendation_feedback_user_record_created",
        table_name="recommendation_feedback",
    )
    op.drop_table("recommendation_feedback")
