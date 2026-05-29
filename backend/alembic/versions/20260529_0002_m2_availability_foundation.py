"""M2 foundation — copies uniqueness + availability_snapshots hypertable.

M1 already shipped the `copies` columns we need (signature, barcode), but
the ingest path never populated them — it inserted one synthetic row per
(record, biblioteca). M2 changes that ingest path to drop one row per
ejemplar with real signature + barcode, so this migration:

1. Adds a partial unique index on (record_id, barcode) — barcodes are
   the library system's natural ID for a physical copy, and the new
   ingest path produces one row per barcode. The partial WHERE keeps
   NULL barcodes (virtual/digital copies) outside the constraint.

2. Creates `availability_snapshots` as a TimescaleDB hypertable
   partitioned on `observed_at`. Append-only time series of how each
   copy's loan status changed over time.

The TimescaleDB extension is created idempotently here as well. The dev
Docker image (timescale/timescaledb-ha:pg16) and the GitHub Actions CI
service both bundle it, but a freshly-created database needs the
explicit CREATE EXTENSION to load the extension into this catalog.

Revision ID: 20260529_0002
Revises: 20260529_0001
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260529_0002"
down_revision: str | Sequence[str] | None = "20260529_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # ───── copies — partial unique on (record_id, barcode) ─────
    op.create_index(
        "ux_copies_record_barcode",
        "copies",
        ["record_id", "barcode"],
        unique=True,
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )

    # ───── availability_snapshots (TimescaleDB hypertable) ─────
    op.create_table(
        "availability_snapshots",
        sa.Column(
            "copy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("copies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        # The OPAC's literal `data-disp` string at observation time — kept
        # so we can audit mapping drift without re-scraping.
        sa.Column("raw_status", sa.Text()),
        sa.Column("due_back_at", sa.Date()),
        sa.PrimaryKeyConstraint("copy_id", "observed_at", name="pk_availability_snapshots"),
    )
    # `create_hypertable` requires that all unique constraints (incl. the
    # PK) include the partitioning column. Our PK is (copy_id, observed_at)
    # so `observed_at` is covered. 7-day chunks keep working sets small
    # for the hourly probe job we'll add in a follow-up commit.
    op.execute(
        """
        SELECT create_hypertable(
            'availability_snapshots',
            'observed_at',
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        )
        """
    )
    op.create_index(
        "ix_availability_snapshots_status",
        "availability_snapshots",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_availability_snapshots_status", table_name="availability_snapshots")
    op.drop_table("availability_snapshots")
    op.drop_index("ux_copies_record_barcode", table_name="copies")
    # We deliberately do NOT drop the timescaledb extension — other
    # databases on the same cluster may rely on it.
