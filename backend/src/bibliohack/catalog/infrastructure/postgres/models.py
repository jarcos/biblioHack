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

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bibliohack.shared.infrastructure.db import Base


class BibliographicRecordModel(Base):
    __tablename__ = "bibliographic_records"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    titn: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text)
    # TEXT (not bounded VARCHAR): upstream records occasionally carry long /
    # multi-valued document-type and language strings that overflowed the old
    # varchar(64)/varchar(8) and aborted the whole ingest run.
    document_type: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    pub_year: Mapped[int | None] = mapped_column(Integer)
    publisher: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)

    # UDC/CDU classification (MARC T080), e.g. '821.134.2-1"19"'. Kept raw so
    # the literary-form classifier — and future genre faceting — can re-read
    # it without a re-crawl.
    classification: Mapped[str | None] = mapped_column(Text)

    # Literary profile (see catalog/domain/literary_profile.py). Stored as the
    # StrEnum *values*; computed at ingest, used to scope search/recommender
    # reads by default. 'unknown' stays inside the default scope, so existing
    # rows (server_default below) remain visible until re-crawled.
    audience: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    literary_form: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    # Coarse genre (see Genre in literary_profile.py) — CDU form division +
    # tejuelos. Backfilled from `classification` in migration 0013; rows whose
    # only signal is a signature stay 'unknown' until their next re-scrape.
    genre: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")

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

    # BGE-M3 dense embedding (1024-d) for semantic search / "more like this".
    # NULL until the embedder processes the record (off the OPAC path).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))

    # Catalogue relevance (Phase R). Precomputed nightly off the OPAC path by
    # the recompute use case; intrinsic to the record (no per-user context).
    # `relevance_score` ∈ [0,1] is the blended rank key (default sort on
    # /browse); `relevance_components` holds the per-component sub-scores for
    # debugging + a future "why this" badge set; `relevance_updated_at` tracks
    # staleness. server_default 0 keeps un-scored rows last until first compute.
    relevance_score: Mapped[float] = mapped_column(Double, nullable=False, server_default=text("0"))
    relevance_components: Mapped[dict[str, float] | None] = mapped_column(JSONB)
    relevance_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
        # Browse facets/filters (the navigator): genre, language, pub_year.
        Index("ix_bibliographic_records_genre", "genre"),
        Index("ix_bibliographic_records_language", "language"),
        Index("ix_bibliographic_records_pub_year", "pub_year"),
        # Ranking index for the relevance-default /browse sort (matches the
        # hand-written DESC index in migration 0014).
        Index("ix_records_relevance", text("relevance_score DESC")),
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


class CanonSeedModel(Base):
    """The canon seed: "works worth having" from external knowledge bases.

    NOT a catalogue record — see ``docs/design/canon-import.md`` and
    ``catalog.domain.canon``. Identity is ``(source, source_ref)`` (e.g.
    ``('wikidata', 'Q12345')``) so a monthly refresh upserts in place. The C1
    matcher fills ``matched_record_id`` / ``matched_via`` when the work is
    already in the mirror; ``acquire_status`` tracks the (later) C3 OPAC path.
    """

    __tablename__ = "canon_seed"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text)
    pub_year: Mapped[int | None] = mapped_column(Integer)
    isbn13: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    awards: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    notability: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # Set by the C1 matcher. NULL = not (yet) matched to a mirror record.
    matched_record_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("bibliographic_records.id", ondelete="SET NULL"),
    )
    matched_via: Mapped[str | None] = mapped_column(String(16))

    acquire_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="unchecked"
    )

    # Open Library ratings count (C4 popularity signal). NULL = not yet checked
    # against OL; 0 = checked, no ratings; >0 = that many. Off-OPAC enrichment.
    ol_rating_count: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Idempotent refresh: upsert by the external identity.
        Index("uq_canon_seed_source_ref", "source", "source_ref", unique=True),
        # Matcher sweeps "still unmatched" rows; coverage report counts by status.
        Index("ix_canon_seed_matched_record_id", "matched_record_id"),
        Index("ix_canon_seed_acquire_status", "acquire_status"),
        # GIN over the ISBN array powers the ISBN-13 match lookup (C1).
        Index("ix_canon_seed_isbn13", "isbn13", postgresql_using="gin"),
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


class DiscoveryCursorModel(Base):
    """How far we've paginated through an expert query's results list.

    One row per expression (e.g. '(@fepu>=2024)'). `next_offset` is the DOC
    offset to resume at next run; advancing it lets discovery march through
    the whole result set across runs instead of re-scanning page 1.
    """

    __tablename__ = "discovery_cursors"

    expression: Mapped[str] = mapped_column(Text, primary_key=True)
    next_offset: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
