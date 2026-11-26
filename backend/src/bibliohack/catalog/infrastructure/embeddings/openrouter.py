"""BGE-M3 via OpenRouter's embeddings API — hosted, no local compute.

Same model and the same 1024-d vectors as the Hugging Face adapter, so the
stored vectors and the HNSW index stay valid; only the provider changes.
Added 2026-11-26 when Hugging Face stopped giving free accounts any Inference
credits (every call answered 402 Payment Required). OpenRouter routes
`baai/bge-m3` to DeepInfra or Parasail at about $0.01 per million tokens, so
embedding the whole ~1.7M-record mirror costs around a dollar, on the key the
app already uses for rationales and query rewriting.

The endpoint is OpenAI-compatible: POST `{base_url}/embeddings` with
`{"model", "input": [...]}`, answer `{"data": [{"index", "embedding"}, ...]}`.
Implements the synchronous `Embedder` port; the embed pipeline decides batch
sizes and pacing.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Sequence

_DIM = 1024
DEFAULT_MODEL = "baai/bge-m3"


class OpenRouterEmbedder:
    """`Embedder` backed by OpenRouter's OpenAI-compatible embeddings API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/embeddings"
        self._model = model
        self._timeout = timeout_seconds

    @property
    def dimensions(self) -> int:
        return _DIM

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(list(texts))

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "input": texts},
            )
        response.raise_for_status()
        vectors = _vectors_in_input_order(response.json())
        if len(vectors) != len(texts):
            msg = f"OpenRouter returned {len(vectors)} embeddings for {len(texts)} inputs"
            raise ValueError(msg)
        return [_l2_normalize(v) for v in vectors]


def _vectors_in_input_order(payload: object) -> list[list[float]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        msg = "unexpected embeddings payload from OpenRouter"
        raise ValueError(msg)
    ordered = sorted(data, key=lambda item: int(item["index"]))
    return [[float(x) for x in item["embedding"]] for item in ordered]


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]
