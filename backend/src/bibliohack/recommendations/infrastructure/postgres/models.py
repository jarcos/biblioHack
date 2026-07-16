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
    SmallInteger,
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


class RecommendationFeedbackModel(Base):
    """The reader's return channel (chat-recs P1, §D4) — one row per event.

    Append-only: a like/dislike/«más como esto»/«no me interesa» each insert a
    new row; the *latest* signal per (user, record) is what re-weights the
    centroid and busts the cache. `signal` is a plain string (see
    `FeedbackSignal`), matching the codebase's enum-ish-column convention.
    `rating` is set only for the P2 `read_rating` signal.
    """

    __tablename__ = "recommendation_feedback"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    signal: Mapped[str] = mapped_column(String(20), nullable=False)
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    # clock_timestamp(), not now(): "latest signal per record wins" orders by
    # this column, and now() is fixed at transaction start — two signals written
    # in one transaction would tie. clock_timestamp() advances per statement, so
    # insertion order is preserved regardless of transaction boundaries.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

    __table_args__ = (
        # The "latest signal per record" read is DISTINCT ON (record_id) ordered
        # by created_at, scoped to the user — a btree on these columns serves it
        # (Postgres scans backward for the desc ordering).
        Index(
            "ix_recommendation_feedback_user_record_created",
            "user_id",
            "record_id",
            "created_at",
        ),
    )
