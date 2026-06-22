"""FastAPI providers for the recommendations ports (overridable in tests)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# Runtime imports — FastAPI evaluates dependency signatures at runtime (see
# the note in identity/interfaces/http/dependencies.py).
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from bibliohack.holdings.infrastructure.postgres.branch_repository import (
    PostgresBranchRepository,
)
from bibliohack.identity.domain.user import User  # noqa: TC001
from bibliohack.identity.interfaces.http.dependencies import get_current_user
from bibliohack.interfaces.http.dependencies import get_tx_session
from bibliohack.recommendations.application.ports import (  # noqa: TC001
    CandidateRetriever,
    RationaleWriter,
    RecommendationRepository,
    ShelfTasteReader,
)
from bibliohack.recommendations.infrastructure.llm.openrouter_rationales import (
    NullRationaleWriter,
    OpenRouterRationaleWriter,
)
from bibliohack.recommendations.infrastructure.postgres.recommendation_repository import (
    PostgresCandidateRetriever,
    PostgresRecommendationRepository,
    PostgresShelfTasteReader,
)
from bibliohack.shared.infrastructure.settings import Settings, get_settings


def get_recommendation_repository(
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> RecommendationRepository:
    return PostgresRecommendationRepository(session)


def get_shelf_taste_reader(
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> ShelfTasteReader:
    return PostgresShelfTasteReader(session)


def get_candidate_retriever(
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> CandidateRetriever:
    return PostgresCandidateRetriever(session)


async def get_caller_branch_codes(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> list[str] | None:
    """The caller's followed branch codes (L4 library-aware recs), or None.

    A dependency (not an inline call) so tests can override it without a DB.
    """
    return await PostgresBranchRepository(session).scope_branch_codes(str(user.id), "mine")


def get_rationale_writer(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RationaleWriter:
    if not settings.openrouter_api_key:
        return NullRationaleWriter()
    return OpenRouterRationaleWriter(
        api_key=settings.openrouter_api_key,
        model=settings.openrouter_model,
        base_url=settings.openrouter_base_url,
    )
