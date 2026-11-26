"""`build_embedder` picks the hosted BGE-M3 adapter from settings."""

from __future__ import annotations

from bibliohack.catalog.infrastructure.embeddings.factory import build_embedder
from bibliohack.catalog.infrastructure.embeddings.huggingface import HuggingFaceEmbedder
from bibliohack.catalog.infrastructure.embeddings.openrouter import OpenRouterEmbedder
from bibliohack.shared.infrastructure.settings import Settings


def _settings(
    *,
    embedding_provider: str = "openrouter",
    openrouter_api_key: str = "",
    huggingface_api_token: str = "",
) -> Settings:
    return Settings.model_validate(
        {
            "embedding_provider": embedding_provider,
            "openrouter_api_key": openrouter_api_key,
            "huggingface_api_token": huggingface_api_token,
        }
    )


def test_openrouter_is_the_default_provider() -> None:
    embedder = build_embedder(_settings(openrouter_api_key="or-key"))

    assert isinstance(embedder, OpenRouterEmbedder)


def test_openrouter_without_a_key_means_no_embedder() -> None:
    # Search then degrades to keyword, as it always has without a provider.
    assert build_embedder(_settings(huggingface_api_token="hf-token")) is None


def test_huggingface_can_still_be_chosen() -> None:
    embedder = build_embedder(
        _settings(embedding_provider="huggingface", huggingface_api_token="hf-token")
    )

    assert isinstance(embedder, HuggingFaceEmbedder)


def test_huggingface_without_a_token_means_no_embedder() -> None:
    assert build_embedder(_settings(embedding_provider="huggingface")) is None
