"""BGE-M3 embedder via sentence-transformers (the `ai` extra).

Heavy (torch + a ~2.3GB model), so it belongs to the embedder plane and
lazy-loads the model on first use — importing this module is cheap; loading
the model isn't. Produces L2-normalized 1024-d vectors, so cosine distance
reduces to a dot product (matching the HNSW `vector_cosine_ops` index).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

_DIM = 1024  # BGE-M3 dense embedding size


class SentenceTransformerEmbedder:
    """`Embedder` backed by a sentence-transformers model (default BGE-M3)."""

    def __init__(self, *, model_name: str = "BAAI/bge-m3", device: str = "cpu") -> None:
        self._model_name = model_name
        self._device = device
        self._model: Any = None  # loaded lazily on first embed

    @property
    def dimensions(self) -> int:
        return _DIM

    def _load(self) -> Any:
        if self._model is None:
            # Lazy import — sentence-transformers (torch) lives in the [ai] extra.
            from sentence_transformers import (  # type: ignore[import-not-found,unused-ignore]
                SentenceTransformer,
            )

            self._model = SentenceTransformer(self._model_name, device=self._device)
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = self._load().encode(text, normalize_embeddings=True, convert_to_numpy=True)
        return list(vector.tolist())
