"""Pydantic response schemas for the recommendations API."""

from __future__ import annotations

from pydantic import BaseModel, Field

# Runtime import (not TYPE_CHECKING): Pydantic resolves this annotation at
# model-build time to construct the nested `record` field.
from bibliohack.catalog.interfaces.http.schemas import CatalogRecordSummarySchema  # noqa: TC001


class RecommendationItemSchema(BaseModel):
    """One suggestion: the catalogue projection + why it surfaced."""

    record: CatalogRecordSummarySchema
    score: float = Field(..., description="Cosine similarity to the user's taste centroid.")
    rationale: str | None = Field(None, description="LLM one-liner; null when unavailable.")


class RecommendationsResponseSchema(BaseModel):
    """The user's current batch.

    `reason` tells the UI why `items` may be empty: `ok` (genuinely nothing
    retrievable yet) vs `empty_profile` (no catalogue-matched books on the
    shelf — the UI should point at the importer).
    """

    reason: str = Field("ok", description="ok | empty_profile.")
    items: list[RecommendationItemSchema] = Field(default_factory=list)
