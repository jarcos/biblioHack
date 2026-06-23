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
    genre: str = Field(
        "unknown", description="narrative | poetry | drama | essay | comic | unknown."
    )
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
    genre: str = Field(
        "unknown", description="narrative | poetry | drama | essay | comic | unknown."
    )
    available_count: int = Field(0, ge=0, description="Copies on the shelf right now.")
    cover: CoverSchema | None = None
    relevance_score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Precomputed catalogue relevance [0,1]; default /browse ranking key.",
    )


class RewrittenIntentSchema(BaseModel):
    """The structured intent a natural-language query was rewritten to (§8.3.1).

    Present on the search response only when an LLM rewrite was *applied* (the
    results came from a faceted browse on these filters). The UI renders a
    revertible chip ("Resultados para autor X… · buscar literalmente"); the
    literal search re-issues the same query with `rewrite=false`.
    """

    author: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    sort: str | None = Field(None, description="Applied ordering: newest | title | relevance.")


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
    rewritten: RewrittenIntentSchema | None = Field(
        None,
        description=(
            "Structured intent the natural-language query was rewritten to, when a "
            "rewrite was applied; null otherwise. Drives the revertible 'showing "
            "results for…' chip."
        ),
    )


class FacetCountSchema(BaseModel):
    """One facet value with its record count."""

    value: str
    count: int = Field(..., ge=0)


class BrowseResponseSchema(BaseModel):
    """A page of the catalogue navigator with facet counts."""

    total: int = Field(..., ge=0, description="Records matching the active filters.")
    limit: int = Field(..., ge=1)
    offset: int = Field(..., ge=0)
    has_more: bool
    items: list[CatalogRecordSummarySchema]
    facets: dict[str, list[FacetCountSchema]] = Field(
        default_factory=dict,
        description=(
            "Per-dimension value counts (genre / language / audience / literary_form), "
            "each computed over the active filters excluding that dimension's own."
        ),
    )


class AuthorCountSchema(BaseModel):
    """An author with how many catalogue records they appear on."""

    name: str
    records: int = Field(..., ge=0)


class AuthorsResponseSchema(BaseModel):
    """Author directory page (most-represented first)."""

    items: list[AuthorCountSchema] = Field(default_factory=list)


class SimilarResponseSchema(BaseModel):
    """ "More like this" — nearest neighbours of a record in embedding space."""

    titn: int = Field(..., description="The anchor record these are similar to.")
    items: list[CatalogRecordSummarySchema] = Field(
        default_factory=list,
        description="Nearest records by cosine distance. Empty if the anchor isn't embedded yet.",
    )
