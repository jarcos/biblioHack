"""FastAPI router for recommendations (/api/recommendations).

Auth-required by design: a recommendation is derived from one user's shelf
and is served only to that user. Under /api/* per the tunnel-routing rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

# Runtime imports — FastAPI evaluates endpoint signatures at runtime (see
# the note in identity/interfaces/http/dependencies.py).
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from bibliohack.catalog.interfaces.http.schemas import CatalogRecordSummarySchema, CoverSchema
from bibliohack.identity.domain.user import User  # noqa: TC001
from bibliohack.identity.interfaces.http.dependencies import get_current_user
from bibliohack.interfaces.http.dependencies import get_tx_session
from bibliohack.recommendations.application.ports import (  # noqa: TC001
    CandidateRetriever,
    RationaleWriter,
    RecommendationRepository,
    ShelfTasteReader,
)
from bibliohack.recommendations.application.use_cases.get_recommendations import (
    GetRecommendations,
)
from bibliohack.recommendations.interfaces.http.dependencies import (
    get_caller_branch_codes,
    get_candidate_retriever,
    get_rationale_writer,
    get_recommendation_repository,
    get_shelf_taste_reader,
)
from bibliohack.recommendations.interfaces.http.schemas import (
    RecommendationItemSchema,
    RecommendationsResponseSchema,
)
from bibliohack.shared.application.result import Err
from bibliohack.shared.infrastructure.settings import Settings, get_settings

if TYPE_CHECKING:
    from bibliohack.catalog.application.dto import CatalogRecordSummary
    from bibliohack.recommendations.domain.recommendation import Recommendation

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("", response_model=RecommendationsResponseSchema)
async def get_recommendations(
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_tx_session)],
    shelf: Annotated[ShelfTasteReader, Depends(get_shelf_taste_reader)],
    retriever: Annotated[CandidateRetriever, Depends(get_candidate_retriever)],
    rationales: Annotated[RationaleWriter, Depends(get_rationale_writer)],
    repository: Annotated[RecommendationRepository, Depends(get_recommendation_repository)],
    library_codes: Annotated[list[str] | None, Depends(get_caller_branch_codes)],
    nearby: Annotated[
        bool,
        Query(description="Only recommend titles borrowable in your followed branches."),
    ] = False,
) -> RecommendationsResponseSchema:
    """The caller's current recommendation batch (cached per shelf state).

    Library-aware (L4): titles borrowable in the user's followed branches are
    boosted up the ranking; `nearby=true` hard-filters to only those. Users who
    follow no branches get the plain taste-based batch.
    """
    result = await GetRecommendations(
        shelf=shelf,
        retriever=retriever,
        rationales=rationales,
        repository=repository,
        limit=settings.recommendations_limit,
    ).execute(str(user.id), library_codes=library_codes, nearby_only=nearby)

    if isinstance(result, Err):
        return RecommendationsResponseSchema(reason=result.error.value, items=[])
    return RecommendationsResponseSchema(reason="ok", items=await _enrich(session, result.value))


async def _enrich(
    session: AsyncSession, recommendations: tuple[Recommendation, ...]
) -> list[RecommendationItemSchema]:
    """Join the catalogue projection (cover + availability) onto each item."""
    if not recommendations:
        return []
    from bibliohack.catalog.infrastructure.postgres.catalog_read_repository import (
        PostgresCatalogReadRepository,
    )

    summaries = await PostgresCatalogReadRepository(session).summaries_by_record_ids(
        [UUID(r.record_id) for r in recommendations]
    )
    items: list[RecommendationItemSchema] = []
    for recommendation in recommendations:
        summary = summaries.get(UUID(recommendation.record_id))
        if summary is None:
            continue  # record pruned since generation — just skip it
        items.append(
            RecommendationItemSchema(
                record=_summary_to_schema(summary),
                score=recommendation.score,
                rationale=recommendation.rationale,
            )
        )
    return items


def _summary_to_schema(summary: CatalogRecordSummary) -> CatalogRecordSummarySchema:
    cover = (
        CoverSchema(status=summary.cover.status, source=summary.cover.source, url=summary.cover.url)
        if summary.cover is not None
        else None
    )
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
        cover=cover,
    )
