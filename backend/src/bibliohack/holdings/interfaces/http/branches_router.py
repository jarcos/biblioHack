"""FastAPI router for branches + per-user follows (Libraries milestone L1).

All paths sit under ``/api/*`` (tunnel rule: frontend-called endpoints must, or
they fall through to the static site and return HTML).

- GET /api/branches      — public list (code, name, municipality, province,
  lat/lng) so the browser can distance-sort client-side for the picker (the
  user's location never leaves the browser).
- GET /api/me/branches   — the caller's followed branch codes.
- PUT /api/me/branches   — replace the caller's follow set (order = preference).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# Runtime imports — FastAPI evaluates endpoint signatures at runtime.
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from bibliohack.holdings.infrastructure.postgres.branch_repository import (
    PostgresBranchRepository,
)
from bibliohack.identity.domain.user import User  # noqa: TC001
from bibliohack.identity.interfaces.http.dependencies import get_current_user
from bibliohack.interfaces.http.dependencies import get_tx_session

router = APIRouter(tags=["branches"])

_MAX_FOLLOWS = 50  # a sane upper bound; nobody follows 500 libraries


class BranchSchema(BaseModel):
    code: str
    name: str
    municipality: str | None = None
    province: str | None = None
    lat: float | None = None
    lng: float | None = None


class BranchListResponse(BaseModel):
    branches: list[BranchSchema]


class FollowedBranchesResponse(BaseModel):
    codes: list[str]


class SetFollowedRequest(BaseModel):
    codes: list[str] = Field(default_factory=list, max_length=_MAX_FOLLOWS)


@router.get("/api/branches", response_model=BranchListResponse)
async def list_branches(
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> BranchListResponse:
    """Every active branch, for the client-side proximity picker (public)."""
    branches = await PostgresBranchRepository(session).list_active()
    return BranchListResponse(
        branches=[
            BranchSchema(
                code=b.code,
                name=b.name,
                municipality=b.municipality,
                province=b.province,
                lat=b.lat,
                lng=b.lng,
            )
            for b in branches
        ]
    )


@router.get("/api/me/branches", response_model=FollowedBranchesResponse)
async def get_my_branches(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> FollowedBranchesResponse:
    """The caller's followed branch codes, in their saved order."""
    codes = await PostgresBranchRepository(session).followed_codes(str(user.id))
    return FollowedBranchesResponse(codes=codes)


@router.put("/api/me/branches", response_model=FollowedBranchesResponse)
async def set_my_branches(
    payload: SetFollowedRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> FollowedBranchesResponse:
    """Replace the caller's follow set. Rejects unknown branch codes."""
    repo = PostgresBranchRepository(session)
    valid = await repo.existing_codes(payload.codes)
    unknown = [c for c in payload.codes if c not in valid]
    if unknown:
        raise HTTPException(
            status_code=422,  # Unprocessable Content
            detail=f"unknown branch codes: {', '.join(sorted(set(unknown)))}",
        )
    await repo.set_followed(str(user.id), payload.codes)
    return FollowedBranchesResponse(codes=await repo.followed_codes(str(user.id)))
