"""SQLAlchemy models for the holdings context.

No `from __future__ import annotations` — see catalog/infrastructure/postgres/models.py
for the rationale.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from bibliohack.shared.infrastructure.db import Base


class BranchModel(Base):
    __tablename__ = "branches"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    municipality: Mapped[str | None] = mapped_column(Text)
    province: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CopyModel(Base):
    __tablename__ = "copies"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_code: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("branches.code"),
        nullable=False,
        index=True,
    )
    signature: Mapped[str | None] = mapped_column(Text)
    barcode: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_copies_record_branch", "record_id", "branch_code"),)
