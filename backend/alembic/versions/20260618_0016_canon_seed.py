"""Canon seed table (phase C0).

Lands ``canon_seed`` — the curated "works worth having" list that drives canon
import (see ``docs/design/canon-import.md`` and ``catalog.domain.canon``). It is
deliberately NOT a catalogue record: external knowledge bases (Wikidata, award
lists, Open Library) seed *which* works are canonical, while the live OPAC stays
the source of truth for *what the libraries hold*. Identity is
``(source, source_ref)`` (unique) so the monthly refresh upserts in place.

``matched_record_id`` / ``matched_via`` are filled by the C1 matcher when the
work is already in the mirror (FK ``ON DELETE SET NULL`` so dropping a record
just unlinks the seed, never deletes it). ``acquire_status`` tracks the later
C3 OPAC acquisition path and defaults to ``unchecked``.

Relies on the pg_trgm / GIN machinery already enabled in
``infra/postgres/init/`` (same as the contributor/title trigram indexes).

Revision ID: 20260618_0016
Revises: 20260617_0015
Create Date: 2026-06-18
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260618_0016"
down_revision: str | Sequence[str] | None = "20260617_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canon_seed",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("pub_year", sa.Integer(), nullable=True),
        sa.Column(
            "isbn13",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "awards",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("notability", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("matched_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("matched_via", sa.String(length=16), nullable=True),
        sa.Column(
            "acquire_status",
            sa.String(length=16),
            server_default="unchecked",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["matched_record_id"],
            ["bibliographic_records.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Idempotent refresh: one seed row per external identity.
    op.create_index(
        "uq_canon_seed_source_ref",
        "canon_seed",
        ["source", "source_ref"],
        unique=True,
    )
    op.create_index("ix_canon_seed_matched_record_id", "canon_seed", ["matched_record_id"])
    op.create_index("ix_canon_seed_acquire_status", "canon_seed", ["acquire_status"])
    # GIN over the ISBN array for the C1 ISBN-13 overlap lookup.
    op.create_index(
        "ix_canon_seed_isbn13",
        "canon_seed",
        ["isbn13"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_canon_seed_isbn13", table_name="canon_seed")
    op.drop_index("ix_canon_seed_acquire_status", table_name="canon_seed")
    op.drop_index("ix_canon_seed_matched_record_id", table_name="canon_seed")
    op.drop_index("uq_canon_seed_source_ref", table_name="canon_seed")
    op.drop_table("canon_seed")
