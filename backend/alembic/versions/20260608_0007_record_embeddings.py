"""Record embeddings for semantic search (pgvector).

Enables the `vector` extension and adds a 1024-dim `embedding` column to
`bibliographic_records` (BGE-M3 produces 1024-d dense vectors), plus an HNSW
index under cosine distance for fast nearest-neighbour search. The column is
nullable — records are embedded asynchronously by the embedder, off the OPAC
path, so most rows start NULL and fill in over time.

Revision ID: 20260608_0007
Revises: 20260608_0006
Create Date: 2026-06-08
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260608_0007"
down_revision: str | Sequence[str] | None = "20260608_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIM = 1024  # BGE-M3 dense embedding size


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "bibliographic_records",
        sa.Column("embedding", Vector(_DIM), nullable=True),
    )
    # HNSW under cosine distance. Embeddings are L2-normalized at write time, so
    # cosine == inner product; cosine keeps it robust if that ever changes.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bibrec_embedding_hnsw "
        "ON bibliographic_records USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_bibrec_embedding_hnsw")
    op.drop_column("bibliographic_records", "embedding")
