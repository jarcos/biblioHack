"""FastAPI router for read-only catalog endpoints.

- GET /catalog/records/{titn}     — full bibliographic record + copies
- GET /catalog/search?q=...        — full-text search over the catalog
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

# AsyncSession needs to be a *runtime* import here because FastAPI uses
# `typing.get_type_hints()` to introspect the dependency annotations on
# each route, and would fail to resolve `AsyncSession` if it lived in a
# TYPE_CHECKING block.
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from bibliohack.catalog.application.use_cases.hybrid_search import HybridSearch
from bibliohack.catalog.application.use_cases.semantic_search import SemanticSearch
from bibliohack.catalog.domain.literary_profile import Audience, Genre, LiteraryForm, SearchScope
from bibliohack.catalog.domain.titn import Titn

# HuggingFaceEmbedder is imported at runtime for the same FastAPI type-hint
# introspection reason as AsyncSession (it appears in a dependency annotation).
from bibliohack.catalog.infrastructure.embeddings.huggingface import (  # noqa: TC001
    HuggingFaceEmbedder,
)
from bibliohack.catalog.infrastructure.postgres.catalog_read_repository import (
    PostgresCatalogReadRepository,
)
from bibliohack.catalog.interfaces.http.schemas import (
    AuthorCountSchema,
    AuthorsResponseSchema,
    BrowseResponseSchema,
    CatalogRecordSchema,
    CatalogRecordSummarySchema,
    CopySchema,
    CoverSchema,
    FacetCountSchema,
    SearchResponseSchema,
    SimilarResponseSchema,
)
from bibliohack.holdings.infrastructure.postgres.branch_repository import (
    PostgresBranchRepository,
)
from bibliohack.identity.domain.user import User  # noqa: TC001 (FastAPI dep introspection)
from bibliohack.identity.interfaces.http.dependencies import get_optional_user
from bibliohack.interfaces.http.dependencies import get_embedder, get_session

if TYPE_CHECKING:
    from bibliohack.catalog.application.dto import (
        CatalogRecordSummary,
        CatalogRecordView,
        SearchPage,
    )

router = APIRouter(prefix="/catalog", tags=["catalog"])


class SearchMode(StrEnum):
    """Requested ranking strategy for /catalog/search."""

    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class BrowseSort(StrEnum):
    """Ordering for /catalog/browse."""

    RELEVANCE = "relevance"
    NEWEST = "newest"
    TITLE = "title"


class LibraryScope(StrEnum):
    """Library scope for /catalog/browse + /catalog/search (Libraries L3).

    Distinct from the literary `scope` (media filter). `mine` is the default:
    for a signed-in user who follows ≥1 branch it hard-filters to records held
    there; for anonymous / no-follow users it resolves to the full catalogue.
    """

    MINE = "mine"
    PROVINCE = "province"
    FULL = "full"


async def _resolve_library_codes(
    session: AsyncSession, user: User | None, level: LibraryScope
) -> list[str] | None:
    """Branch codes to hard-filter on, or None for the full catalogue.

    None whenever there's no session, the user follows nothing, or `full` is
    requested — so the feature degrades cleanly to the whole mirror.
    """
    if user is None or level is LibraryScope.FULL:
        return None
    return await PostgresBranchRepository(session).scope_branch_codes(str(user.id), level.value)


@router.get(
    "/records/{titn}",
    response_model=CatalogRecordSchema,
    responses={404: {"description": "TITN not present in our mirror."}},
)
async def get_record(
    titn: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogRecordSchema:
    """Return the full bibliographic record for a TITN, with copies and branches."""
    if titn < 1:
        raise HTTPException(
            # Starlette 1.2 renamed HTTP_422_UNPROCESSABLE_ENTITY -> CONTENT;
            # the numeric code (422) is unchanged. Using the new name keeps
            # us free of the deprecation warning that pytest promotes to error.
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="TITN must be a positive integer",
        )
    repo = PostgresCatalogReadRepository(session)
    view = await repo.find_by_titn(Titn(titn))
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No record with TITN={titn} in the mirror yet",
        )
    return _record_to_schema(view)


@router.get(
    "/search",
    response_model=SearchResponseSchema,
)
async def search_catalog(
    q: Annotated[str, Query(min_length=1, description="Free-text search query.")],
    session: Annotated[AsyncSession, Depends(get_session)],
    embedder: Annotated[HuggingFaceEmbedder | None, Depends(get_embedder)],
    user: Annotated[User | None, Depends(get_optional_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    scope: Annotated[
        SearchScope,
        Query(description="'literary' (default: adult literature, all genres) or 'all'."),
    ] = SearchScope.LITERARY,
    library_scope: Annotated[
        LibraryScope,
        Query(description="'mine' (followed branches, default), 'province', or 'full'."),
    ] = LibraryScope.MINE,
    mode: Annotated[
        SearchMode,
        Query(
            description=(
                "'keyword' (FTS, default), 'semantic' (BGE-M3 vector KNN) or "
                "'hybrid' (Reciprocal Rank Fusion of both)."
            ),
        ),
    ] = SearchMode.KEYWORD,
) -> SearchResponseSchema:
    """Search the catalogue by keyword (FTS), meaning (vectors), or both fused.

    `keyword` (default) ranks by `ts_rank_cd` against the `spanish_unaccent`
    tsquery. `semantic` embeds the query with BGE-M3 and ranks by cosine
    distance to record embeddings (pgvector KNN) — finding records by meaning
    even without a literal term match. `hybrid` fuses both rankings with
    Reciprocal Rank Fusion: exact-title precision *and* by-meaning recall;
    note its pagination is bounded by the fused candidate pool. If `semantic`
    or `hybrid` is requested but the embedder isn't configured, the response
    falls back to `keyword` and the `mode` field reports what actually ran.
    `scope` defaults to `literary` (hides confidently children's/youth or
    non-fiction); pass `scope=all` for the whole mirror.
    """
    repo = PostgresCatalogReadRepository(session)
    library_codes = await _resolve_library_codes(session, user, library_scope)

    if mode is SearchMode.HYBRID and embedder is not None:
        page = await HybridSearch(read_repo=repo, embedder=embedder).execute(
            query=q, limit=limit, offset=offset, scope=scope, library_branch_codes=library_codes
        )
        return _page_to_schema(page, mode=SearchMode.HYBRID)

    if mode is SearchMode.SEMANTIC and embedder is not None:
        page = await SemanticSearch(read_repo=repo, embedder=embedder).execute(
            query=q, limit=limit, offset=offset, scope=scope, library_branch_codes=library_codes
        )
        return _page_to_schema(page, mode=SearchMode.SEMANTIC)

    # keyword, or semantic/hybrid requested without an embedder → fall back.
    page = await repo.search(
        query=q, limit=limit, offset=offset, scope=scope, library_branch_codes=library_codes
    )
    return _page_to_schema(page, mode=SearchMode.KEYWORD)


@router.get(
    "/browse",
    response_model=BrowseResponseSchema,
)
async def browse_catalog(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_optional_user)],
    author: Annotated[
        str | None, Query(description="Exact contributor name, as returned by /catalog/authors.")
    ] = None,
    language: Annotated[str | None, Query(max_length=16)] = None,
    genre: Annotated[Genre | None, Query()] = None,
    audience: Annotated[Audience | None, Query()] = None,
    literary_form: Annotated[LiteraryForm | None, Query()] = None,
    year_from: Annotated[int | None, Query(ge=0, le=2100)] = None,
    year_to: Annotated[int | None, Query(ge=0, le=2100)] = None,
    available: Annotated[
        bool, Query(description="Only records with at least one copy on a shelf right now.")
    ] = False,
    sort: Annotated[BrowseSort, Query()] = BrowseSort.RELEVANCE,
    library_scope: Annotated[
        LibraryScope,
        Query(description="'mine' (followed branches, default), 'province', or 'full'."),
    ] = LibraryScope.MINE,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BrowseResponseSchema:
    """The catalogue navigator: filter + facet the whole mirror, no query needed.

    Covers the full mirror (no implicit literary scope — the audience and
    literary-form facets are the explicit levers here). Facet counts are
    computed per dimension over the other active filters, so picking a value
    never zeroes out its siblings.

    Default ordering is `relevance` (the precomputed `relevance_score`), so the
    best titles lead instead of "newest TITN first"; `newest` and `title` remain
    available. Each row carries `available_count`/`copies_count` for the
    availability badge, and the `available` flag is the "available now" quick
    filter (latest snapshot == available on any branch).
    """
    repo = PostgresCatalogReadRepository(session)
    library_codes = await _resolve_library_codes(session, user, library_scope)
    page = await repo.browse(
        author=author,
        language=language,
        genre=genre.value if genre is not None else None,
        audience=audience.value if audience is not None else None,
        literary_form=literary_form.value if literary_form is not None else None,
        year_from=year_from,
        year_to=year_to,
        available_only=available,
        sort=sort.value,
        limit=limit,
        offset=offset,
        library_branch_codes=library_codes,
    )
    return BrowseResponseSchema(
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
        items=[_summary_to_schema(item) for item in page.items],
        facets={
            dim: [FacetCountSchema(value=f.value, count=f.count) for f in counts]
            for dim, counts in page.facets.items()
        },
    )


@router.get(
    "/authors",
    response_model=AuthorsResponseSchema,
)
async def list_authors(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[
        str | None, Query(min_length=2, max_length=120, description="Substring of the name.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> AuthorsResponseSchema:
    """Author directory — distinct names with record counts, most-represented first."""
    repo = PostgresCatalogReadRepository(session)
    authors = await repo.authors(query=q, limit=limit)
    return AuthorsResponseSchema(
        items=[AuthorCountSchema(name=a.name, records=a.records) for a in authors]
    )


@router.get(
    "/records/{titn}/similar",
    response_model=SimilarResponseSchema,
)
async def get_similar(
    titn: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
    scope: Annotated[
        SearchScope,
        Query(description="'literary' (default) or 'all'."),
    ] = SearchScope.LITERARY,
) -> SimilarResponseSchema:
    """ "Más como este" — records nearest to `titn` in embedding space.

    A pure pgvector KNN over the anchor record's stored BGE-M3 vector (no model
    call needed), excluding the record itself. Returns an empty `items` list
    when the record is unknown or hasn't been embedded yet — the frontend then
    simply hides the strip.
    """
    if titn < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="TITN must be a positive integer",
        )
    repo = PostgresCatalogReadRepository(session)
    items = await repo.similar_to(Titn(titn), limit=limit, scope=scope)
    return SimilarResponseSchema(
        titn=titn,
        items=[_summary_to_schema(item) for item in items],
    )


# ─── helpers ─────────────────────────────────────────────────


def _cover_to_schema(cover: object) -> CoverSchema | None:
    # `cover` is a CoverView | None (typed loosely to avoid importing the DTO
    # at runtime just for an isinstance).
    if cover is None:
        return None
    return CoverSchema(status=cover.status, source=cover.source, url=cover.url)  # type: ignore[attr-defined]


def _record_to_schema(view: CatalogRecordView) -> CatalogRecordSchema:
    return CatalogRecordSchema(
        titn=view.titn,
        title=view.title,
        subtitle=view.subtitle,
        document_type=view.document_type,
        language=view.language,
        pub_year=view.pub_year,
        publisher=view.publisher,
        classification=view.classification,
        audience=view.audience,
        literary_form=view.literary_form,
        authors=list(view.authors),
        subjects=list(view.subjects),
        isbns=list(view.isbns),
        copies=[
            CopySchema(
                branch_code=c.branch_code,
                branch_name=c.branch_name,
                signature=c.signature,
                status=c.status,
                due_back_at=c.due_back_at,
            )
            for c in view.copies
        ],
        source_url=view.source_url,
        cover=_cover_to_schema(view.cover),
    )


def _summary_to_schema(summary: CatalogRecordSummary) -> CatalogRecordSummarySchema:
    return CatalogRecordSummarySchema(
        titn=summary.titn,
        title=summary.title,
        authors=list(summary.authors),
        publisher=summary.publisher,
        pub_year=summary.pub_year,
        copies_count=summary.copies_count,
        audience=summary.audience,
        literary_form=summary.literary_form,
        available_count=summary.available_count,
        cover=_cover_to_schema(summary.cover),
        relevance_score=summary.relevance_score,
    )


def _page_to_schema(page: SearchPage, *, mode: SearchMode) -> SearchResponseSchema:
    return SearchResponseSchema(
        query=page.query,
        mode=mode.value,
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
        items=[_summary_to_schema(item) for item in page.items],
    )
