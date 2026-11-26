"""Pick the hosted BGE-M3 adapter from settings (composition root helper).

Every caller that needs vectors — the embed backfill, semantic/hybrid search,
cold-start recommendations — goes through here, so a provider switch is one
setting (`EMBEDDING_PROVIDER`) and not an edit in three places. Returns None
when the chosen provider has no credential; callers already treat that as
"no semantic search" and degrade to keyword.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.catalog.infrastructure.embeddings.huggingface import HuggingFaceEmbedder
from bibliohack.catalog.infrastructure.embeddings.openrouter import OpenRouterEmbedder

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import Embedder
    from bibliohack.shared.infrastructure.settings import Settings


def build_embedder(settings: Settings) -> Embedder | None:
    if settings.embedding_provider == "huggingface":
        if not settings.huggingface_api_token:
            return None
        return HuggingFaceEmbedder(
            api_token=settings.huggingface_api_token,
            endpoint=settings.huggingface_embedding_endpoint,
        )
    if not settings.openrouter_api_key:
        return None
    return OpenRouterEmbedder(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_embedding_model,
    )
