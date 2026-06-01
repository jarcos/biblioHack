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
    """One copy in a branch — minimal info for read endpoints."""

    branch_code: str
    branch_name: str


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
    authors: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    isbns: tuple[str, ...] = ()
    copies: tuple[CopyView, ...] = ()
    source_url: str = ""


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
