"""Coarse genre tag on bibliographic records (catalog navigator, Tier B).

Adds `genre` (narrative/poetry/drama/essay/comic/unknown) plus the browse
indexes (genre, language, pub_year). Backfills from the raw CDU
`classification` column with SQL-only rules mirroring
`catalog/domain/literary_profile.derive_genre`'s CDU branch:

- 741.5…           → comic
- 8[26]…-1<digit?> → poetry / -2 drama / -3 narrative / -4 essay

Rows whose only genre signal is a copy signature stay 'unknown' here and
get the full (CDU + tejuelo) derivation on their next re-scrape — the same
classify-don't-discard / re-derive-without-re-crawl deal as audience and
literary_form in migration 0003.

Revision ID: 20260611_0013
Revises: 20260610_0012
Create Date: 2026-06-11
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260611_0013"
down_revision: str | Sequence[str] | None = "20260610_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bibliographic_records",
        sa.Column("genre", sa.String(length=16), server_default="unknown", nullable=False),
    )
    op.create_index("ix_bibliographic_records_genre", "bibliographic_records", ["genre"])
    op.create_index("ix_bibliographic_records_language", "bibliographic_records", ["language"])
    op.create_index("ix_bibliographic_records_pub_year", "bibliographic_records", ["pub_year"])

    # Backfill from the CDU we already store. `substring(... from regex)`
    # pulls the form division digit after a literature class (82…/86…).
    op.execute(
        r"""
        UPDATE bibliographic_records
        SET genre = CASE
            WHEN classification LIKE '741.5%' THEN 'comic'
            ELSE COALESCE(
                CASE substring(trim(classification) from '^8[26][0-9.]*-([0-9])')
                    WHEN '1' THEN 'poetry'
                    WHEN '2' THEN 'drama'
                    WHEN '3' THEN 'narrative'
                    WHEN '4' THEN 'essay'
                END,
                'unknown'
            )
        END
        WHERE classification IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_bibliographic_records_pub_year", table_name="bibliographic_records")
    op.drop_index("ix_bibliographic_records_language", table_name="bibliographic_records")
    op.drop_index("ix_bibliographic_records_genre", table_name="bibliographic_records")
    op.drop_column("bibliographic_records", "genre")
