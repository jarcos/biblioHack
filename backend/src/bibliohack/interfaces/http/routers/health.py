"""Health and version endpoints.

Kept deliberately minimal: a real readiness check (DB / Redis pings) lands in
M1 when those dependencies actually exist at runtime.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from bibliohack import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Minimal liveness response."""

    status: Literal["ok"]
    version: str


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness probe. Always returns 200 if the process is up."""
    return HealthResponse(status="ok", version=__version__)


@router.get("/version", response_model=HealthResponse)
async def version() -> HealthResponse:
    """Version endpoint — same payload as /healthz, separate URL for clarity."""
    return HealthResponse(status="ok", version=__version__)
