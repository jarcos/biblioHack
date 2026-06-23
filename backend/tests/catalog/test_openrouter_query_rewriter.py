"""OpenRouterQueryRewriter tests — httpx.MockTransport, no network."""

from __future__ import annotations

import json

import httpx

from bibliohack.catalog.infrastructure.llm.openrouter_query_rewriter import (
    NullQueryRewriter,
    OpenRouterQueryRewriter,
)


def _rewriter(handler: httpx.MockTransport) -> OpenRouterQueryRewriter:
    return OpenRouterQueryRewriter(api_key="test-key", model="test/model", transport=handler)


def _completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_parses_author_and_sort() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("Authorization")
        return _completion('{"author": "Yuval Noah Harari", "sort": "newest"}')

    rewritten = await _rewriter(httpx.MockTransport(handler)).rewrite("lo último de Sapiens")

    assert rewritten is not None
    assert rewritten.author == "Yuval Noah Harari"
    assert rewritten.sort == "newest"
    assert rewritten.is_structured
    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["messages"][1]["content"] == "lo último de Sapiens"


async def test_parses_year_range_and_cleaned_query() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _completion(
            '{"year_from": 1990, "year_to": 1999, "cleaned_query": "misterio Sevilla"}'
        )

    rewritten = await _rewriter(httpx.MockTransport(handler)).rewrite(
        "novelas de misterio de los 90 ambientadas en Sevilla"
    )
    assert rewritten is not None
    assert rewritten.year_from == 1990
    assert rewritten.year_to == 1999
    assert rewritten.cleaned_query == "misterio Sevilla"


async def test_tolerates_fenced_json() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _completion('Claro:\n```json\n{"author": "Cela"}\n```')

    rewritten = await _rewriter(httpx.MockTransport(handler)).rewrite("libros de Cela")
    assert rewritten is not None
    assert rewritten.author == "Cela"


async def test_drops_invalid_sort_and_implausible_year() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _completion('{"author": "X", "sort": "popularidad", "year_from": 3000}')

    rewritten = await _rewriter(httpx.MockTransport(handler)).rewrite("algo de X muy popular")
    assert rewritten is not None
    assert rewritten.author == "X"
    assert rewritten.sort is None  # 'popularidad' is not a valid /browse ordering
    assert rewritten.year_from is None  # 3000 is outside the plausibility band


async def test_empty_object_returns_none() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _completion("{}")

    assert await _rewriter(httpx.MockTransport(handler)).rewrite("hola") is None


async def test_any_failure_returns_none() -> None:
    def http_500(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    def not_json(_request: httpx.Request) -> httpx.Response:
        return _completion("lo siento, no puedo")

    for handler in (http_500, not_json):
        assert await _rewriter(httpx.MockTransport(handler)).rewrite("lo último de X") is None


async def test_no_key_or_blank_query_skips_the_call() -> None:
    assert await OpenRouterQueryRewriter(api_key="", model="m").rewrite("lo último de X") is None
    assert await NullQueryRewriter().rewrite("lo último de X") is None
