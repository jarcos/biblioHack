"""SQLAlchemy model for the `availability_snapshots` hypertable.

No `from __future__ import annotations` — see catalog/infrastructure/postgres/models.py
for the rationale (SQLAlchemy 2.0 resolves Mapped[T] at runtime).
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from bibliohack.shared.infrastructure.db import Base


class AvailabilitySnapshotModel(Base):
    """One observation of one copy's loan status at a point in time.

    Append-only. The (copy_id, observed_at) primary key doubles as the
    Timescale partition declaration — see the M2 Alembic migration where
    we call `create_hypertable()`.
    """

    __tablename__ = "availability_snapshots"

    copy_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("copies.id", ondelete="CASCADE"),
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # The OPAC's literal `data-disp` string at observation time — kept
    # for audit; the domain enum on `status` is what callers read.
    raw_status: Mapped[str | None] = mapped_column(Text)
    due_back_at: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        PrimaryKeyConstraint("copy_id", "observed_at", name="pk_availability_snapshots"),
        Index("ix_availability_snapshots_status", "status"),
    )
