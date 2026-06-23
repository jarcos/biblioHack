"""OpenRouter `QueryRewriter` — natural language → structured search (§8.3.1).

One chat call turns "lo último de Sapiens" into ``author="Yuval Noah Harari",
sort="newest"`` so the search can route to a faceted browse instead of a
literal full-text match. Best-effort by contract: any failure (HTTP, timeout,
malformed JSON, model rambling) or a query with no extractable structure
returns ``None``, and the caller falls back to a plain search — the rewriter
can never make search worse, only better.

User-facing, so it runs per request on the free tier; the caller gates the
call behind a cheap heuristic (`should_rewrite`) so short keyword queries
never pay the round-trip.
"""

from __future__ import annotations

import json

import httpx
import structlog

from bibliohack.catalog.application.dto import RewrittenQuery
from bibliohack.catalog.domain.pub_year import max_plausible_pub_year

# The /browse orderings the rewriter is allowed to request. Anything else the
# model invents is dropped (we never trust free-form sort strings).
_VALID_SORTS = frozenset({"newest", "title", "relevance"})

_SYSTEM_PROMPT = (
    "Eres el analizador de consultas de un catálogo de bibliotecas españolas. "
    "Conviertes la búsqueda en lenguaje natural de una persona en filtros "
    "estructurados. Responde SOLO con un objeto JSON con estas claves "
    "opcionales:\n"
    '- "author": nombre completo y canónico del autor si la consulta lo nombra '
    "o lo implica (p. ej. «lo último de Sapiens» → «Yuval Noah Harari»); si no, omítela.\n"
    '- "year_from" / "year_to": enteros (año de publicación) cuando se acote un '
    "periodo («de los 90» → 1990 y 1999; «desde 2010» → year_from 2010).\n"
    '- "sort": uno de "newest" (lo más reciente / lo último / lo nuevo), '
    '"title" (orden alfabético) o "relevance"; omítela si no se pide orden.\n'
    '- "cleaned_query": el tema o términos libres que queden tras extraer lo '
    "anterior (p. ej. «novelas de misterio ambientadas en Sevilla» → «misterio Sevilla»); "
    "omítela si no queda texto útil.\n"
    "No inventes filtros que la consulta no respalde. Si no hay nada que "
    "estructurar, responde {}. Sin texto adicional, solo el JSON."
)


class OpenRouterQueryRewriter:
    """Concrete `QueryRewriter` over OpenRouter's chat completions API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 12.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport  # injectable for tests

    async def rewrite(self, query: str) -> RewrittenQuery | None:
        cleaned = query.strip()
        if not self._api_key or not cleaned:
            return None
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
                            {"role": "user", "content": cleaned},
                        ],
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            return _parse(str(content))
        except Exception as exc:  # best-effort by contract (see module docstring)
            structlog.get_logger().warning(
                "catalog.query_rewrite_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None


class NullQueryRewriter:
    """No-API-key fallback: never rewrites, search runs the literal query."""

    async def rewrite(self, query: str) -> RewrittenQuery | None:
        return None


def _parse(content: str) -> RewrittenQuery | None:
    """Parse the model's JSON object into a validated RewrittenQuery, or None.

    Tolerates code fences / prose around the object. Returns None when the
    object is empty or carries nothing usable (so the caller runs the literal
    query). Years are sanity-bounded; an unknown sort is dropped, not honoured.
    """
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed: object = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    author = _clean_str(parsed.get("author"))
    cleaned_query = _clean_str(parsed.get("cleaned_query"))
    sort = _clean_str(parsed.get("sort"))
    sort = sort.lower() if sort else None
    year_from = _clean_year(parsed.get("year_from"))
    year_to = _clean_year(parsed.get("year_to"))

    rewritten = RewrittenQuery(
        cleaned_query=cleaned_query,
        author=author,
        year_from=year_from,
        year_to=year_to,
        sort=sort if sort in _VALID_SORTS else None,
    )
    # Nothing structured AND no cleaned text → no point rewriting.
    if not rewritten.is_structured and not rewritten.cleaned_query:
        return None
    return rewritten


def _clean_str(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clean_year(value: object) -> int | None:
    """A plausible publication year (1000..current+1), else None.

    Mirrors the catalogue's own future-year plausibility band so a rewrite
    can't ask for years the catalogue would never store.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1000 <= value <= max_plausible_pub_year() else None
