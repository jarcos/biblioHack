"""Pydantic response schemas for the public catalog API.

The HTTP layer owns the wire format. Internal DTOs from
`catalog/application/dto.py` are mapped onto these schemas at the router
boundary so the application stays Pydantic-free.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CopySchema(BaseModel):
    """One physical/virtual copy at a branch."""

    branch_code: str = Field(..., description="AbsysNET branch code, e.g. 'JA23'.")
    branch_name: str = Field(..., description="Human-readable branch name.")
    signature: str | None = Field(None, description="Shelf mark / tejuelo, e.g. 'N ARS roh'.")
    status: str = Field(
        "unknown",
        description="Latest availability: available | loaned | reserved | unavailable | unknown.",
    )
    due_back_at: str | None = Field(None, description="ISO date the copy is due back, if loaned.")


class CoverSchema(BaseModel):
    """Cover state for a record. `url` is set only when `status == 'resolved'`."""

    status: str = Field(..., description="resolved | nofound | pending | failed | unknown.")
    source: str = Field("unknown", description="openlibrary | googlebooks | placeholder | unknown.")
    url: str | None = Field(
        None, description="Served, content-addressed cover URL when resolved, else null."
    )


class CatalogRecordSchema(BaseModel):
    """Full bibliographic record + its copies."""

    titn: int = Field(..., description="Upstream TITN identifier.")
    title: str
    subtitle: str | None = None
    document_type: str | None = None
    language: str | None = Field(None, description="ISO 639-3 when known.")
    pub_year: int | None = None
    publisher: str | None = None
    classification: str | None = Field(None, description="UDC classification (T080).")
    audience: str = Field("unknown", description="adult | youth | children | unknown.")
    literary_form: str = Field("unknown", description="literary | nonfiction | unknown.")
    authors: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)
    isbns: list[str] = Field(default_factory=list)
    copies: list[CopySchema] = Field(default_factory=list)
    source_url: str = Field(..., description="OPAC URL the record was originally scraped from.")
    cover: CoverSchema | None = None


class CatalogRecordSummarySchema(BaseModel):
    """Search-result row — fewer fields than the full record."""

    titn: int
    title: str
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    pub_year: int | None = None
    copies_count: int = 0
    audience: str = Field("unknown", description="adult | youth | children | unknown.")
    literary_form: str = Field("unknown", description="literary | nonfiction | unknown.")
    available_count: int = Field(0, ge=0, description="Copies on the shelf right now.")
    cover: CoverSchema | None = None


class SearchResponseSchema(BaseModel):
    """A page of search results."""

    query: str
    mode: str = Field(
        "keyword",
        description=(
            "Effective ranking used: 'keyword' (FTS) or 'semantic' (vector KNN). "
            "May differ from the requested mode if semantic search is unavailable."
        ),
    )
    total: int = Field(..., ge=0, description="Total matching records across all pages.")
    limit: int = Field(..., ge=1)
    offset: int = Field(..., ge=0)
    has_more: bool
    items: list[CatalogRecordSummarySchema]


class SimilarResponseSchema(BaseModel):
    """ "More like this" — nearest neighbours of a record in embedding space."""

    titn: int = Field(..., description="The anchor record these are similar to.")
    items: list[CatalogRecordSummarySchema] = Field(
        default_factory=list,
        description="Nearest records by cosine distance. Empty if the anchor isn't embedded yet.",
    )
