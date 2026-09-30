"""Move catalogue relevance to its own narrow table (Phase R, fix).

The nightly `relevance recompute` had been timing out every night since the
mirror grew past ~1M records (freshness 10+ weeks, coverage 17%). The cause is
the write, not the maths: the score lived on `bibliographic_records`, and
`relevance_score` is indexed, so every rewrite is a non-HOT update that
re-inserts the row into all eleven indexes — the 1.3 GB HNSW embedding index,
the 393 MB title trigram GIN, the FTS GIN, … — and recomputes the stored
`fts` column. Measured on prod: ~30 rows/s, i.e. ~16 h for 1.7M rows against
a 30 min job budget.

This migration moves the three relevance columns into `record_relevance`
(PK + one `score DESC` index), where the same nightly rewrite is a set-based
upsert over a narrow table.

- `record_relevance` is backfilled from the existing columns, so current
  scores survive (unscored rows keep score 0 / `updated_at` NULL).
- An AFTER INSERT trigger on `bibliographic_records` seeds a row for every new
  record, so readers can INNER JOIN. That matters: with the join, the
  relevance-default /browse walks `ix_record_relevance_score` (~40 ms on prod);
  a LEFT JOIN + COALESCE forces a full sort of the catalogue (~4.7 s).
- `ix_records_relevance` and the three old columns are dropped.
- The Grafana read-only role (`metrics`), when present, gets SELECT on the new
  table so the relevance panels don't go "No data".

Revision ID: 20260930_0024
Revises: 20260716_0023
Create Date: 2026-09-30
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260930_0024"
down_revision: str | Sequence[str] | None = "20260716_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "record_relevance",
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Double(), server_default=sa.text("0"), nullable=False),
        sa.Column("components", postgresql.JSONB(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["record_id"], ["bibliographic_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("record_id"),
    )
    op.execute(
        """
        INSERT INTO record_relevance (record_id, score, components, updated_at)
        SELECT id, relevance_score, relevance_components, relevance_updated_at
        FROM bibliographic_records
        """
    )
    op.create_index(
        "ix_record_relevance_score",
        "record_relevance",
        [sa.text("score DESC")],
    )
    op.execute(
        """
        CREATE FUNCTION record_relevance_seed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO record_relevance (record_id) VALUES (NEW.id)
            ON CONFLICT (record_id) DO NOTHING;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_record_relevance_seed
        AFTER INSERT ON bibliographic_records
        FOR EACH ROW EXECUTE FUNCTION record_relevance_seed()
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metrics') THEN
                GRANT SELECT ON record_relevance TO metrics;
            END IF;
        END
        $$
        """
    )
    op.drop_index("ix_records_relevance", table_name="bibliographic_records")
    op.drop_column("bibliographic_records", "relevance_updated_at")
    op.drop_column("bibliographic_records", "relevance_components")
    op.drop_column("bibliographic_records", "relevance_score")


def downgrade() -> None:
    op.add_column(
        "bibliographic_records",
        sa.Column("relevance_score", sa.Double(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "bibliographic_records",
        sa.Column("relevance_components", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "bibliographic_records",
        sa.Column("relevance_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE bibliographic_records b
        SET relevance_score = rr.score,
            relevance_components = rr.components,
            relevance_updated_at = rr.updated_at
        FROM record_relevance rr
        WHERE rr.record_id = b.id AND rr.updated_at IS NOT NULL
        """
    )
    op.create_index(
        "ix_records_relevance",
        "bibliographic_records",
        [sa.text("relevance_score DESC")],
    )
    op.execute("DROP TRIGGER IF EXISTS trg_record_relevance_seed ON bibliographic_records")
    op.execute("DROP FUNCTION IF EXISTS record_relevance_seed()")
    op.drop_index("ix_record_relevance_score", table_name="record_relevance")
    op.drop_table("record_relevance")
