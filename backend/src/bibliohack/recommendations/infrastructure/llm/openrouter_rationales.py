"""OpenRouter `RationaleWriter` — one chat call decorates a whole batch.

Strictly best-effort by contract: any failure (HTTP, timeout, malformed
JSON, model rambling) returns `{}` and the recommendations ship without
prose. Candidates are numbered in the prompt and mapped back by index —
LLMs garble UUIDs but can count.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bibliohack.recommendations.application.ports import Candidate

_SYSTEM_PROMPT = (
    "Eres una bibliotecaria andaluza con muy buen ojo. Para cada libro candidato, "
    "escribe UNA sola frase en español (máx. 25 palabras) explicando por qué le "
    "puede gustar a esta persona dado lo que ha leído. Responde SOLO con un objeto "
    'JSON: las claves son los números de candidato como cadenas ("1", "2", …) y '
    "los valores la frase. Sin texto adicional."
)


class OpenRouterRationaleWriter:
    """Concrete `RationaleWriter` over OpenRouter's chat completions API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 25.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport  # injectable for tests

    async def write(
        self, *, liked_books: Sequence[str], candidates: Sequence[Candidate]
    ) -> dict[str, str]:
        if not self._api_key or not candidates:
            return {}
        prompt = self._build_prompt(liked_books, candidates)
        try:
            client = (
                httpx.AsyncClient(timeout=self._timeout, transport=self._transport)
                if self._transport is not None
                else httpx.AsyncClient(timeout=self._timeout)
            )
            async with client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            return self._map_back(str(content), candidates)
        except Exception as exc:  # best-effort by contract (see module docstring)
            structlog.get_logger().warning(
                "recommendations.rationales_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return {}

    @staticmethod
    def _build_prompt(liked_books: Sequence[str], candidates: Sequence[Candidate]) -> str:
        liked = "\n".join(f"- {book}" for book in liked_books[:15])
        numbered = "\n".join(
            f"{index}. {candidate.title}" + (f" — {candidate.author}" if candidate.author else "")
            for index, candidate in enumerate(candidates, start=1)
        )
        return f"Libros que le han gustado:\n{liked}\n\nCandidatos:\n{numbered}"

    @staticmethod
    def _map_back(content: str, candidates: Sequence[Candidate]) -> dict[str, str]:
        # Tolerate code fences / prose around the JSON object.
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end <= start:
            return {}
        parsed: object = json.loads(content[start : end + 1])
        if not isinstance(parsed, dict):
            return {}
        rationales: dict[str, str] = {}
        for index, candidate in enumerate(candidates, start=1):
            value = parsed.get(str(index))
            if isinstance(value, str) and value.strip():
                rationales[candidate.record_id] = value.strip()
        return rationales


class NullRationaleWriter:
    """No-API-key fallback: recommendations without prose."""

    async def write(
        self, *, liked_books: Sequence[str], candidates: Sequence[Candidate]
    ) -> dict[str, str]:
        return {}
