"""BGE-M3 via the HuggingFace Inference API — hosted, no local compute.

Same 1024-d BGE-M3 vectors as the local adapter (so the schema is unchanged),
but the model runs on HF — the NAS only makes an HTTPS call, keeping the
~2.3GB model off its constrained RAM. Vectors are L2-normalized so cosine
distance reduces to a dot product (matching the HNSW `vector_cosine_ops` index).

`wait_for_model` covers HF's cold-start (the model may take ~20s to load on the
first call after idle). Implements the synchronous `Embedder` port; the embed
pipeline decides batch sizes and any rate-limit pacing.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Sequence

_DIM = 1024
_DEFAULT_ENDPOINT = "https://api-inference.huggingface.co/models/BAAI/bge-m3"


class HuggingFaceEmbedder:
    """`Embedder` backed by the HuggingFace Inference API (BGE-M3)."""

    def __init__(
        self,
        *,
        api_token: str,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._token = api_token
        self._endpoint = endpoint
        self._timeout = timeout_seconds

    @property
    def dimensions(self) -> int:
        return _DIM

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(list(texts))

    def embed_query(self, text: str) -> list[float]:
        result = self._embed([text])
        return result[0] if result else []

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._token}"},
                json={"inputs": texts, "options": {"wait_for_model": True}},
            )
        response.raise_for_status()
        payload = response.json()
        return [_l2_normalize(_to_sentence_vector(item)) for item in payload]


def _to_sentence_vector(item: object) -> list[float]:
    """Coerce one HF result into a single sentence vector.

    Sentence-transformers feature-extraction usually returns a pooled vector
    (list[float]); if HF returns token-level output (list[list[float]]) we
    mean-pool over tokens.
    """
    if isinstance(item, list) and item and isinstance(item[0], list):
        rows = item
        cols = len(rows[0])
        return [sum(float(row[i]) for row in rows) / len(rows) for i in range(cols)]
    if isinstance(item, list):
        return [float(x) for x in item]
    msg = "unexpected embedding shape from HuggingFace"
    raise ValueError(msg)


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]
