"""SQLAlchemy models for the holdings context.

No `from __future__ import annotations` — see catalog/infrastructure/postgres/models.py
for the rationale.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
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
    province: Mapped[str | None] = mapped_column(Text, index=True)
    # Geo/contact enrichment (Libraries milestone L0). lat/lng filled off-OPAC by
    # `holdings enrich-branches`; the rest reserved for an official directory feed.
    address: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    url: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    opening_hours: Mapped[str | None] = mapped_column(Text)
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


class UserFollowedBranchModel(Base):
    """A branch a user follows (Libraries milestone L1). PK = (user, branch)."""

    __tablename__ = "user_followed_branches"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    branch_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("branches.code"), primary_key=True
    )
    position: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_user_followed_branches_user_id", "user_id"),)
