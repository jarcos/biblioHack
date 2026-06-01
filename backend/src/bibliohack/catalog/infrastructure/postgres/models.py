"""SQLAlchemy models for the catalog context + the scrape state tables.

These are persistence concerns; they are NOT the domain. The mapping between
domain entities and these models happens in the repository implementations
(landing in the next commit).

We deliberately do NOT use `from __future__ import annotations` here — SQLAlchemy
2.0 resolves `Mapped[T]` types at registry configuration time and needs the
referenced classes to be real (importable, evaluable) at runtime. Forward
references between models use string literals where needed.

Conventions:
- Surrogate UUID primary keys, generated client-side (we own identity).
- `titn` is UNIQUE — the upstream identifier.
- Timezone-aware timestamps everywhere.
- Cascading deletes from `bibliographic_records` to its children.
- A generated `tsvector` column for FTS, populated server-side from the
  Spanish-unaccent text-search config seeded in `infra/postgres/init/`.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bibliohack.shared.infrastructure.db import Base


class BibliographicRecordModel(Base):
    __tablename__ = "bibliographic_records"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    titn: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str | None] = mapped_column(String(8))
    pub_year: Mapped[int | None] = mapped_column(Integer)
    publisher: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)

    # UDC/CDU classification (MARC T080), e.g. '821.134.2-1"19"'. Kept raw so
    # the literary-form classifier — and future genre faceting — can re-read
    # it without a re-crawl.
    classification: Mapped[str | None] = mapped_column(String(64))

    # Literary profile (see catalog/domain/literary_profile.py). Stored as the
    # StrEnum *values*; computed at ingest, used to scope search/recommender
    # reads by default. 'unknown' stays inside the default scope, so existing
    # rows (server_default below) remain visible until re-crawled.
    audience: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    literary_form: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")

    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Denormalised author names (space-joined, in order), kept in sync by
    # the ingest repository so we can include them in the generated FTS
    # tsvector below. A Postgres GENERATED column can only reference
    # columns in its own row, so we cannot pull from `contributors`
    # directly — `authors_text` is the bridge.
    authors_text: Mapped[str | None] = mapped_column(Text)

    # Generated full-text-search column, populated by Postgres using the
    # Spanish-unaccent configuration seeded in infra/postgres/init/01-extensions.sql.
    fts: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('spanish_unaccent', "
            "coalesce(title, '') || ' ' || "
            "coalesce(subtitle, '') || ' ' || "
            "coalesce(publisher, '') || ' ' || "
            "coalesce(summary, '') || ' ' || "
            "coalesce(authors_text, ''))",
            persisted=True,
        ),
    )

    # Forward refs via string literals — these classes are defined later in the file.
    contributors: Mapped[list["ContributorModel"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
        order_by="ContributorModel.order_index",
    )
    subjects: Mapped[list["SubjectModel"]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )
    isbns: Mapped[list["IsbnModel"]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_bibliographic_records_fts", "fts", postgresql_using="gin"),
        Index(
            "ix_bibliographic_records_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        # Supports the default "literary" scope filter on search/listing.
        Index("ix_bibliographic_records_scope", "audience", "literary_form"),
    )


class ContributorModel(Base):
    __tablename__ = "contributors"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="author")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    record: Mapped[BibliographicRecordModel] = relationship(back_populates="contributors")

    __table_args__ = (
        Index(
            "ix_contributors_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )


class SubjectModel(Base):
    __tablename__ = "subjects"

    record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject: Mapped[str] = mapped_column(Text, primary_key=True)

    record: Mapped[BibliographicRecordModel] = relationship(back_populates="subjects")


class IsbnModel(Base):
    __tablename__ = "isbns"

    record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bibliographic_records.id", ondelete="CASCADE"),
        primary_key=True,
    )
    isbn: Mapped[str] = mapped_column(String(13), primary_key=True)

    record: Mapped[BibliographicRecordModel] = relationship(back_populates="isbns")


class ScrapeTaskModel(Base):
    """State table for the discovery / refresh loop. See ARCHITECTURE.md §6.7."""

    __tablename__ = "scrape_tasks"

    # autoincrement=False: TITN comes from the OPAC, never from a local sequence.
    titn: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="discovered")
    source_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    source_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    refresh_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_scrape_tasks_status", "status"),
        Index("ix_scrape_tasks_next_retry_at", "next_retry_at"),
        Index("ix_scrape_tasks_refresh_due_at", "refresh_due_at"),
    )


class ScrapeLogModel(Base):
    """One row per HTTP request to the OPAC. Drives daily-cap and latency stats."""

    __tablename__ = "scrape_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    titn: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    bytes_in: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
