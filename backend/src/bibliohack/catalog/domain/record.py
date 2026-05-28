"""BibliographicRecord — the catalog's aggregate root.

A record is what the OPAC calls a "documento": a title (with optional
subtitle), one or more contributors, a publisher, a publication year, zero
or more ISBNs, zero or more subjects, and some free-text description.

The record OWNS its child value objects (contributors, isbns, subjects).
They never live independently. Holdings (copies) and Availability snapshots
are *separate aggregates* in their own bounded contexts, referenced by id.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

from bibliohack.shared.domain import Entity, Identifier

if TYPE_CHECKING:
    from bibliohack.catalog.domain.contributor import Contributor
    from bibliohack.catalog.domain.isbn import Isbn
    from bibliohack.catalog.domain.titn import Titn


@dataclass(frozen=True, slots=True)
class BibliographicRecordId(Identifier):
    """Internal UUID identifier for a BibliographicRecord.

    Distinct from `Titn` — Titn is the *upstream* permalink at AbsysNET;
    this is *our* identifier. Two layers, two purposes.
    """


class BibliographicRecord(Entity[BibliographicRecordId]):
    """The aggregate root for a single bibliographic record.

    Not a dataclass — `dataclass(slots=True)` interacts badly with the
    `super().__init__()` call we need to set up the Entity identity. Plain
    class with explicit attribute initialisation is clearer anyway.
    """

    def __init__(
        self,
        *,
        entity_id: BibliographicRecordId,
        titn: Titn,
        title: str,
        subtitle: str | None = None,
        document_type: str | None = None,
        language: str | None = None,
        pub_year: int | None = None,
        publisher: str | None = None,
        summary: str | None = None,
        contributors: list[Contributor] | None = None,
        subjects: list[str] | None = None,
        isbns: list[Isbn] | None = None,
        source_url: str = "",
        source_hash: bytes = b"",
        first_seen_at: datetime | None = None,
        last_seen_at: datetime | None = None,
    ) -> None:
        super().__init__(entity_id)
        if not title.strip():
            msg = "BibliographicRecord must have a non-empty title"
            raise ValueError(msg)
        # Bounds are intentionally loose — we'd rather store an oddity than
        # reject a real record. The OPAC has plenty of pre-modern facsimiles.
        min_plausible_year = 1400
        max_plausible_year = 2100
        if pub_year is not None and not (min_plausible_year <= pub_year <= max_plausible_year):
            msg = f"Implausible publication year: {pub_year}"
            raise ValueError(msg)
        now = datetime.now(tz=UTC)
        self.titn = titn
        self.title = title.strip()
        self.subtitle = subtitle.strip() if subtitle else None
        self.document_type = document_type
        self.language = language
        self.pub_year = pub_year
        self.publisher = publisher.strip() if publisher else None
        self.summary = summary
        self.contributors: list[Contributor] = list(contributors or [])
        self.subjects: list[str] = list(subjects or [])
        self.isbns: list[Isbn] = list(isbns or [])
        self.source_url = source_url
        self.source_hash = source_hash
        self.first_seen_at = first_seen_at or now
        self.last_seen_at = last_seen_at or now

    # ───────────────────────────────────────────────────────────
    # Factory — the canonical way to create a record from a scrape
    # ───────────────────────────────────────────────────────────

    @classmethod
    def new_from_scrape(
        cls,
        *,
        titn: Titn,
        title: str,
        source_url: str,
        source_hash: bytes,
        **kwargs: object,
    ) -> Self:
        """Create a record that was just scraped for the first time."""
        return cls(
            entity_id=BibliographicRecordId.new(),
            titn=titn,
            title=title,
            source_url=source_url,
            source_hash=source_hash,
            **kwargs,  # type: ignore[arg-type]
        )

    # ───────────────────────────────────────────────────────────
    # Update operations — domain-meaningful mutations
    # ───────────────────────────────────────────────────────────

    def touch(self) -> None:
        """Mark that we've observed this record again, even if nothing changed."""
        self.last_seen_at = datetime.now(tz=UTC)

    def apply_refresh(
        self,
        *,
        title: str,
        subtitle: str | None,
        document_type: str | None,
        language: str | None,
        pub_year: int | None,
        publisher: str | None,
        summary: str | None,
        contributors: list[Contributor],
        subjects: list[str],
        isbns: list[Isbn],
        source_hash: bytes,
    ) -> None:
        """Apply an update from a fresh scrape, preserving identity and timestamps."""
        if not title.strip():
            msg = "BibliographicRecord must have a non-empty title"
            raise ValueError(msg)
        self.title = title.strip()
        self.subtitle = subtitle.strip() if subtitle else None
        self.document_type = document_type
        self.language = language
        self.pub_year = pub_year
        self.publisher = publisher.strip() if publisher else None
        self.summary = summary
        self.contributors = list(contributors)
        self.subjects = list(subjects)
        self.isbns = list(isbns)
        self.source_hash = source_hash
        self.last_seen_at = datetime.now(tz=UTC)

    @property
    def primary_author(self) -> Contributor | None:
        """First author-role contributor, if any. Used as a denormalised hint."""
        from bibliohack.catalog.domain.contributor import ContributorRole

        return next(
            (c for c in self.contributors if c.role is ContributorRole.AUTHOR),
            None,
        )
