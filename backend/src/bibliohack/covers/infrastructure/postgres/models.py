"""SQLAlchemy model for the `covers` metadata table (§7.5.5).

No `from __future__ import annotations` — SQLAlchemy 2.0 resolves Mapped[T]
at runtime (see catalog/infrastructure/postgres/models.py for the rationale).

Only metadata lives here; the image bytes are in the CoverStore, addressed by
`sha256`. Keyed by ISBN-13 (one cover per ISBN; editions sharing a cover
dedup automatically at the content-addressed store).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from bibliohack.shared.infrastructure.db import Base


class CoverModel(Base):
    __tablename__ = "covers"

    isbn_13: Mapped[str] = mapped_column(String(13), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    record_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    license: Mapped[str | None] = mapped_column(Text)
    # Hex sha256 content address into the CoverStore; set only when RESOLVED.
    sha256: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NOFOUND/FAILED are re-tried on a slow cadence (used by a later slice).
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_covers_status", "status"),)
