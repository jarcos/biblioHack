"""M1 initial — catalog + holdings + scrape state tables.

Creates the schema needed to ingest the AbsysNET catalog:

- bibliographic_records (+ tsvector FTS column + GIN indexes)
- contributors / subjects / isbns (child tables of bibliographic_records)
- branches (lookup) + copies (foreign keys to branches and records)
- scrape_tasks (discovery / refresh state machine)
- scrape_log (one row per HTTP request, for rate-limit accounting)

The `vector`, `pg_trgm`, `unaccent`, and `spanish_unaccent` extensions are
expected to be present already (seeded by infra/postgres/init/01-extensions.sql).
We `CREATE EXTENSION IF NOT EXISTS` defensively so this migration is safe
to run against a fresh DB too.

Revision ID: 20260528_0000
Revises:
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260528_0000"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ───── Required extensions (idempotent) ─────
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")
    # Ensure the spanish_unaccent FTS config exists even on a DB that wasn't
    # seeded by docker-compose (e.g. CI without the init script).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_ts_config WHERE cfgname = 'spanish_unaccent'
            ) THEN
                CREATE TEXT SEARCH CONFIGURATION spanish_unaccent (COPY = spanish);
                ALTER TEXT SEARCH CONFIGURATION spanish_unaccent
                    ALTER MAPPING FOR hword, hword_part, word
                    WITH unaccent, spanish_stem;
            END IF;
        END
        $$;
        """
    )

    # ───── branches ─────
    op.create_table(
        "branches",
        sa.Column("code", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("municipality", sa.Text()),
        sa.Column("province", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ───── bibliographic_records ─────
    op.create_table(
        "bibliographic_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("titn", sa.Integer(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("subtitle", sa.Text()),
        sa.Column("document_type", sa.String(length=64)),
        sa.Column("language", sa.String(length=8)),
        sa.Column("pub_year", sa.Integer()),
        sa.Column("publisher", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "fts",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('spanish_unaccent', "
                "coalesce(title, '') || ' ' || "
                "coalesce(subtitle, '') || ' ' || "
                "coalesce(publisher, '') || ' ' || "
                "coalesce(summary, ''))",
                persisted=True,
            ),
        ),
    )
    op.create_index(
        "ix_bibliographic_records_titn",
        "bibliographic_records",
        ["titn"],
    )
    op.create_index(
        "ix_bibliographic_records_fts",
        "bibliographic_records",
        ["fts"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_bibliographic_records_title_trgm",
        "bibliographic_records",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )

    # ───── contributors ─────
    op.create_table(
        "contributors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="author"),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_contributors_record_id", "contributors", ["record_id"])
    op.create_index(
        "ix_contributors_name_trgm",
        "contributors",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )

    # ───── subjects ─────
    op.create_table(
        "subjects",
        sa.Column(
            "record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("subject", sa.Text(), primary_key=True),
    )

    # ───── isbns ─────
    op.create_table(
        "isbns",
        sa.Column(
            "record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("isbn", sa.String(length=13), primary_key=True),
    )

    # ───── copies ─────
    op.create_table(
        "copies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "branch_code",
            sa.String(length=32),
            sa.ForeignKey("branches.code"),
            nullable=False,
        ),
        sa.Column("signature", sa.Text()),
        sa.Column("barcode", sa.String(length=64)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_copies_record_id", "copies", ["record_id"])
    op.create_index("ix_copies_branch_code", "copies", ["branch_code"])
    op.create_index("ix_copies_record_branch", "copies", ["record_id", "branch_code"])

    # ───── scrape_tasks ─────
    op.create_table(
        "scrape_tasks",
        # autoincrement=False: TITN comes from the OPAC, never from a local sequence.
        sa.Column("titn", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="discovered",
        ),
        sa.Column("source_hash", sa.LargeBinary(length=32)),
        sa.Column("source_seen_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("refresh_due_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_scrape_tasks_status", "scrape_tasks", ["status"])
    op.create_index("ix_scrape_tasks_next_retry_at", "scrape_tasks", ["next_retry_at"])
    op.create_index("ix_scrape_tasks_refresh_due_at", "scrape_tasks", ["refresh_due_at"])

    # ───── scrape_log ─────
    op.create_table(
        "scrape_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("titn", sa.Integer()),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("bytes_in", sa.Integer()),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_scrape_log_observed_at", "scrape_log", ["observed_at"])


def downgrade() -> None:
    # Drop in reverse FK order.
    op.drop_table("scrape_log")
    op.drop_table("scrape_tasks")
    op.drop_table("copies")
    op.drop_table("isbns")
    op.drop_table("subjects")
    op.drop_table("contributors")
    op.drop_table("bibliographic_records")
    op.drop_table("branches")
    # We deliberately do NOT drop pg_trgm / unaccent / spanish_unaccent —
    # other migrations or operators may depend on them.
