"""SQLAlchemy model for the `recommendations` table (identity Phase 4 / M5).

No `from __future__ import annotations` — SQLAlchemy 2.0 resolves Mapped[T]
at runtime (see catalog/infrastructure/postgres/models.py).

`cache_key` fingerprints the shelf state the batch was generated from; rows
whose key no longer matches the live shelf are simply ignored and replaced
on the next request.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from bibliohack.shared.infrastructure.db import Base


class RecommendationModel(Base):
    __tablename__ = "recommendations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    matched_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # Cold-start "tastes" chips (§8.3.3), denormalised onto each row of a batch
    # so a cache hit can still surface them. NULL for taste-centroid batches.
    inferred_tastes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "matched_record_id", name="uq_recommendations_user_record"),
        Index("ix_recommendations_user_id", "user_id"),
    )
