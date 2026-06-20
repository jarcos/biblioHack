"""Open Library rating count on canon_seed (phase C4).

Adds ``canon_seed.ol_rating_count`` — the Open Library ratings count for a seed
work, a popularity signal that deepens the canon notability (see
``docs/design/canon-import.md`` → Sources / C4). Nullable on purpose:

- ``NULL``  = not yet checked against Open Library (the enrich job's work queue),
- ``0``     = checked, Open Library has no ratings,
- ``> 0``   = checked, that many ratings.

Populated off-OPAC by ``bibliohack catalog canon enrich-ratings``. Storing it is
decoupled from feeding it into the relevance blend (a later, isolated change),
so this migration only lands the column.

Revision ID: 20260620_0017
Revises: 20260618_0016
Create Date: 2026-06-20
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260620_0017"
down_revision: str | Sequence[str] | None = "20260618_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "canon_seed",
        sa.Column("ol_rating_count", sa.Integer(), nullable=True),
    )
    # Partial index over the enrich job's work queue (rows still unchecked).
    op.create_index(
        "ix_canon_seed_ol_unrated",
        "canon_seed",
        ["id"],
        postgresql_where=sa.text("ol_rating_count IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_canon_seed_ol_unrated", table_name="canon_seed")
    op.drop_column("canon_seed", "ol_rating_count")
