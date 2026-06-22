"""User-followed branches join table (Libraries milestone — phase L1).

Lets a user follow one or more RBPA branches (see
``docs/design/relevance-and-libraries.html`` → Phase L / L1). The follow set
later scopes browse/search/recommendations to «my libraries → province → full».

- PK ``(user_id, branch_code)`` — a user follows each branch at most once.
- ``user_id`` FK → ``users`` ON DELETE CASCADE (GDPR delete drops the follows).
- ``branch_code`` FK → ``branches`` (codes are stable; no cascade needed).
- ``position`` is an optional display-order hint the picker may set.

Revision ID: 20260622_0019
Revises: 20260622_0018
Create Date: 2026-06-22
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260622_0019"
down_revision: str | Sequence[str] | None = "20260622_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_followed_branches",
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("branch_code", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_code"], ["branches.code"]),
        sa.PrimaryKeyConstraint("user_id", "branch_code"),
    )
    # Fast "branches followed by this user" lookups (the scope filter's hot path).
    op.create_index("ix_user_followed_branches_user_id", "user_followed_branches", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_followed_branches_user_id", table_name="user_followed_branches")
    op.drop_table("user_followed_branches")
