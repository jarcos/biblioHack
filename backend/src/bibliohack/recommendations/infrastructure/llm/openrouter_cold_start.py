"""OpenRouter `ColdStartClassifier` — taste from a new user's shelf (§8.3.3).

When a freshly-imported shelf has no catalogue-matched books yet, the taste
centroid can't be built. One chat call reads the raw titles and returns a
free-text taste descriptor (which we embed to retrieve candidates by meaning)
plus a handful of short genre/topic phrases for the UI's "detectamos que te
gusta…" chips.

Best-effort by contract: any failure (HTTP, timeout, malformed JSON) or a
blank descriptor returns ``None``, and the caller falls back to today's
empty-profile response — cold-start never errors a recommendations request.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import structlog

from bibliohack.recommendations.application.ports import ColdStartProfile

if TYPE_CHECKING:
    from collections.abc import Sequence

# Cap the titles we send — enough signal for a taste read, bounded prompt.
_MAX_TITLES = 40

_SYSTEM_PROMPT = (
    "Eres una bibliotecaria andaluza con muy buen ojo. A partir de los libros "
    "que alguien ha guardado en su estantería, deduces sus gustos de lectura. "
    "Responde SOLO con un objeto JSON con dos claves:\n"
    '- "descriptor": una frase en español (máx. 40 palabras) que describa sus '
    "gustos —géneros, temas, tono, épocas— como si fuera a buscar libros "
    "parecidos para esta persona.\n"
    '- "tastes": una lista de 3 a 6 etiquetas cortas en español (1-3 palabras '
    'cada una), p. ej. ["novela histórica", "ciencia ficción", "ensayo divulgativo"].\n'
    "Sin texto adicional, solo el JSON."
)


class OpenRouterColdStartClassifier:
    """Concrete `ColdStartClassifier` over OpenRouter's chat completions API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport  # injectable for tests

    async def infer(self, shelf_titles: Sequence[str]) -> ColdStartProfile | None:
        if not self._api_key or not shelf_titles:
            return None
        prompt = "Libros en su estantería:\n" + "\n".join(
            f"- {title}" for title in shelf_titles[:_MAX_TITLES]
        )
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
            return _parse(str(content))
        except Exception as exc:  # best-effort by contract (see module docstring)
            structlog.get_logger().warning(
                "recommendations.cold_start_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None


class NullColdStartClassifier:
    """No-API-key fallback: never infers, recommendations stay empty-profile."""

    async def infer(self, shelf_titles: Sequence[str]) -> ColdStartProfile | None:
        return None


def _parse(content: str) -> ColdStartProfile | None:
    """Parse the model's JSON into a ColdStartProfile, or None when unusable."""
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed: object = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    descriptor = parsed.get("descriptor")
    if not isinstance(descriptor, str) or not descriptor.strip():
        return None
    raw_tastes = parsed.get("tastes")
    tastes = (
        tuple(t.strip() for t in raw_tastes if isinstance(t, str) and t.strip())
        if isinstance(raw_tastes, list)
        else ()
    )
    return ColdStartProfile(descriptor=descriptor.strip(), tastes=tastes)
