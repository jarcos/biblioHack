"""DTOs for the read side of the catalog.

These are application-layer view objects — the HTTP router maps them onto
Pydantic schemas, but the application doesn't depend on Pydantic / FastAPI.

`CatalogRecordView` is the full per-record payload (used by the detail
endpoint). `CatalogRecordSummary` is the lightweight row shape used by
search results — same identity, fewer fields, cheaper to load.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CopyView:
    """One copy in a branch — minimal info for read endpoints.

    `status` is the *latest* availability snapshot for this copy (the
    availability bounded context's `AvailabilityStatus` value); it defaults
    to ``"unknown"`` when we have no snapshot yet. `due_back_at` is the ISO
    date the copy is expected back when loaned, when the OPAC reported it.
    """

    branch_code: str
    branch_name: str
    signature: str | None = None
    status: str = "unknown"
    due_back_at: str | None = None


@dataclass(frozen=True, slots=True)
class CoverView:
    """Cover state for a record (resolved asynchronously, off the OPAC path).

    `url` is the served cover URL when `status == "resolved"`, else None — the
    frontend renders the image when present and a placeholder otherwise.
    `source` is which provider it came from (openlibrary | googlebooks |
    placeholder | unknown).
    """

    status: str
    source: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogRecordView:
    """Full read-side projection of a `bibliographic_records` row."""

    titn: int
    title: str
    subtitle: str | None = None
    document_type: str | None = None
    language: str | None = None
    pub_year: int | None = None
    publisher: str | None = None
    classification: str | None = None
    audience: str = "unknown"
    literary_form: str = "unknown"
    genre: str = "unknown"
    authors: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    isbns: tuple[str, ...] = ()
    copies: tuple[CopyView, ...] = ()
    source_url: str = ""
    cover: CoverView | None = None


@dataclass(frozen=True, slots=True)
class CatalogRecordSummary:
    """Lightweight shape for search result lists."""

    titn: int
    title: str
    authors: tuple[str, ...]
    publisher: str | None
    pub_year: int | None
    copies_count: int
    audience: str = "unknown"
    literary_form: str = "unknown"
    genre: str = "unknown"
    # How many copies are on the shelf right now (latest snapshot == available).
    available_count: int = 0
    cover: CoverView | None = None


@dataclass(frozen=True, slots=True)
class FacetCount:
    """One value of a browse facet with its record count."""

    value: str
    count: int


@dataclass(frozen=True, slots=True)
class BrowsePage:
    """One page of the catalogue navigator, with facet counts.

    `facets` maps a facet name (genre / language / audience / literary_form)
    to its value counts, each computed over the active filters *excluding*
    that facet's own — the standard faceted-navigation contract, so picking
    a value never zeroes out its siblings.
    """

    items: tuple[CatalogRecordSummary, ...]
    total: int
    limit: int
    offset: int
    facets: dict[str, tuple[FacetCount, ...]]

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


@dataclass(frozen=True, slots=True)
class AuthorCount:
    """An author name with how many catalogue records they appear on."""

    name: str
    records: int


@dataclass(frozen=True, slots=True)
class SearchPage:
    """One page of search results."""

    query: str
    items: tuple[CatalogRecordSummary, ...]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total
