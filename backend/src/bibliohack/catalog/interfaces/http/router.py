"""FastAPI router for read-only catalog endpoints.

- GET /catalog/records/{titn}     — full bibliographic record + copies
- GET /catalog/search?q=...        — full-text search over the catalog
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

# AsyncSession needs to be a *runtime* import here because FastAPI uses
# `typing.get_type_hints()` to introspect the dependency annotations on
# each route, and would fail to resolve `AsyncSession` if it lived in a
# TYPE_CHECKING block.
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from bibliohack.catalog.domain.literary_profile import SearchScope
from bibliohack.catalog.domain.titn import Titn
from bibliohack.catalog.infrastructure.postgres.catalog_read_repository import (
    PostgresCatalogReadRepository,
)
from bibliohack.catalog.interfaces.http.schemas import (
    CatalogRecordSchema,
    CatalogRecordSummarySchema,
    CopySchema,
    SearchResponseSchema,
)
from bibliohack.interfaces.http.dependencies import get_session

if TYPE_CHECKING:
    from bibliohack.catalog.application.dto import (
        CatalogRecordSummary,
        CatalogRecordView,
        SearchPage,
    )

router = APIRouter(prefix="/catalog", tags=["catalog"])


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
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    scope: Annotated[
        SearchScope,
        Query(description="'literary' (default: adult literature, all genres) or 'all'."),
    ] = SearchScope.LITERARY,
) -> SearchResponseSchema:
    """Full-text search over title + subtitle + publisher + summary.

    Ranked by `ts_rank_cd` against the `spanish_unaccent` tsquery — most
    relevant first. Use `limit` + `offset` to paginate. `scope` defaults to
    `literary`, which hides records confidently classified as children's/
    youth or non-fiction; pass `scope=all` to search the whole mirror.
    """
    repo = PostgresCatalogReadRepository(session)
    page = await repo.search(query=q, limit=limit, offset=offset, scope=scope)
    return _page_to_schema(page)


# ─── helpers ─────────────────────────────────────────────────


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
    )


def _page_to_schema(page: SearchPage) -> SearchResponseSchema:
    return SearchResponseSchema(
        query=page.query,
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
        items=[_summary_to_schema(item) for item in page.items],
    )
