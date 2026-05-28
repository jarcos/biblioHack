"""M1.1 — fold author names into the bibliographic_records FTS index.

The initial migration generated `bibliographic_records.fts` from
title + subtitle + publisher + summary only, which meant a search for
"García Márquez" returned zero rows even when the catalog contained
his work. Authors live in a child table (`contributors`), and a Postgres
GENERATED column can only reference columns in its own row, so we
denormalise the author names onto the parent row as `authors_text` and
include that column in the new `fts` expression.

`authors_text` is maintained by the ingest path on every parse so it
stays consistent with the contributors table. It's a private detail of
the FTS pipeline — readers should still go through `contributors`.

Steps:
  1. Add `bibliographic_records.authors_text` (nullable text).
  2. Backfill it for existing rows from `contributors` (role='author',
     ordered by `order_index`, joined with spaces).
  3. Drop the GIN index on the old `fts`, drop the old `fts` column.
  4. Re-add `fts` as a GENERATED tsvector that now coalesces in
     `authors_text` alongside title / subtitle / publisher / summary.
  5. Recreate the GIN index.

Revision ID: 20260529_0001
Revises: 20260528_0000
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260529_0001"
down_revision: str | Sequence[str] | None = "20260528_0000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Kept as a constant so upgrade() and downgrade() can't drift.
_OLD_FTS_EXPR = (
    "to_tsvector('spanish_unaccent', "
    "coalesce(title, '') || ' ' || "
    "coalesce(subtitle, '') || ' ' || "
    "coalesce(publisher, '') || ' ' || "
    "coalesce(summary, ''))"
)
_NEW_FTS_EXPR = (
    "to_tsvector('spanish_unaccent', "
    "coalesce(title, '') || ' ' || "
    "coalesce(subtitle, '') || ' ' || "
    "coalesce(publisher, '') || ' ' || "
    "coalesce(summary, '') || ' ' || "
    "coalesce(authors_text, ''))"
)


def upgrade() -> None:
    # 1. Denormalised authors column on the parent row.
    op.add_column(
        "bibliographic_records",
        sa.Column("authors_text", sa.Text(), nullable=True),
    )

    # 2. Backfill from the contributors table.
    op.execute(
        """
        UPDATE bibliographic_records br
        SET authors_text = sub.joined
        FROM (
            SELECT record_id,
                   string_agg(name, ' ' ORDER BY order_index) AS joined
            FROM contributors
            WHERE role = 'author'
            GROUP BY record_id
        ) AS sub
        WHERE br.id = sub.record_id
        """
    )

    # 3. Drop the dependent GIN index, then the old generated column.
    op.drop_index("ix_bibliographic_records_fts", table_name="bibliographic_records")
    op.drop_column("bibliographic_records", "fts")

    # 4. Re-add the generated tsvector, this time including authors_text.
    op.add_column(
        "bibliographic_records",
        sa.Column(
            "fts",
            postgresql.TSVECTOR(),
            sa.Computed(_NEW_FTS_EXPR, persisted=True),
        ),
    )

    # 5. Recreate the GIN index.
    op.create_index(
        "ix_bibliographic_records_fts",
        "bibliographic_records",
        ["fts"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    # Mirror of upgrade() in reverse: drop the augmented fts + index,
    # restore the original fts expression, then drop authors_text.
    op.drop_index("ix_bibliographic_records_fts", table_name="bibliographic_records")
    op.drop_column("bibliographic_records", "fts")

    op.add_column(
        "bibliographic_records",
        sa.Column(
            "fts",
            postgresql.TSVECTOR(),
            sa.Computed(_OLD_FTS_EXPR, persisted=True),
        ),
    )
    op.create_index(
        "ix_bibliographic_records_fts",
        "bibliographic_records",
        ["fts"],
        postgresql_using="gin",
    )

    op.drop_column("bibliographic_records", "authors_text")
