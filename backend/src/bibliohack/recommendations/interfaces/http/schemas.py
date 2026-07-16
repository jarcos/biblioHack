"""Pydantic request/response schemas for the recommendations API."""

from __future__ import annotations

from typing import Literal

# Runtime import (not TYPE_CHECKING): Pydantic resolves the `UUID` field
# annotations at model-build time, so the name must exist at runtime.
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, Field

# Runtime import (not TYPE_CHECKING): Pydantic resolves this annotation at
# model-build time to construct the nested `record` field.
from bibliohack.catalog.interfaces.http.schemas import CatalogRecordSummarySchema  # noqa: TC001


class RecommendationItemSchema(BaseModel):
    """One suggestion: the catalogue projection + why it surfaced."""

    record_id: UUID = Field(
        ..., description="The catalogue record's id — echo it back to POST feedback."
    )
    record: CatalogRecordSummarySchema
    score: float = Field(..., description="Cosine similarity to the user's taste centroid.")
    rationale: str | None = Field(None, description="LLM one-liner; null when unavailable.")


class RecommendationsResponseSchema(BaseModel):
    """The user's current batch.

    `reason` tells the UI why `items` may be empty: `ok` (genuinely nothing
    retrievable yet) vs `empty_profile` (no catalogue-matched books on the
    shelf — the UI should point at the importer).

    `cold_start` is True when the batch was inferred from the raw imported
    shelf (no catalogue-matched books yet, §8.3.3) — necessarily weaker than
    taste-based recs, so the UI labels it and shows `inferred_tastes` as
    "detectamos que te gusta…" chips. `inferred_tastes` is populated only on a
    freshly generated cold-start batch (not persisted across the cache).
    """

    reason: str = Field("ok", description="ok | empty_profile.")
    cold_start: bool = Field(
        False, description="True when these are LLM cold-start recs (no matched shelf yet)."
    )
    inferred_tastes: list[str] = Field(
        default_factory=list,
        description="Genre/topic chips inferred from the shelf on a fresh cold-start batch.",
    )
    items: list[RecommendationItemSchema] = Field(default_factory=list)


class FeedbackRequestSchema(BaseModel):
    """A single feedback press on a recommended record (chat-recs P1, §D4).

    `signal` is constrained to the four button signals P1 exposes — the
    `read_rating` value exists in the domain enum but is P2's mark-read writer,
    so it is not accepted here. `record_id` is the catalogue record's UUID (the
    same id the item cards render from).
    """

    record_id: UUID
    signal: Literal["like", "dislike", "more_like_this", "not_interested"]


class FeedbackResponseSchema(BaseModel):
    """Ack for a recorded signal. The refreshed batch is fetched separately —
    the signal has already busted the cache, so the next GET regenerates."""

    ok: bool = True
