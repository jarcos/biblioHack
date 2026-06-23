"""OpenRouterColdStartClassifier tests — httpx.MockTransport, no network."""

from __future__ import annotations

import httpx

from bibliohack.recommendations.infrastructure.llm.openrouter_cold_start import (
    NullColdStartClassifier,
    OpenRouterColdStartClassifier,
)

TITLES = ("Patria — Aramburu", "Los pilares de la tierra — Ken Follett")


def _classifier(handler: httpx.MockTransport) -> OpenRouterColdStartClassifier:
    return OpenRouterColdStartClassifier(api_key="test-key", model="test/model", transport=handler)


def _completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_parses_descriptor_and_tastes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer test-key"
        return _completion(
            '{"descriptor": "novela histórica y dramas contemporáneos", '
            '"tastes": ["novela histórica", "drama"]}'
        )

    profile = await _classifier(httpx.MockTransport(handler)).infer(TITLES)
    assert profile is not None
    assert profile.descriptor == "novela histórica y dramas contemporáneos"
    assert profile.tastes == ("novela histórica", "drama")


async def test_tolerates_fenced_json_and_drops_non_string_tastes() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _completion('```json\n{"descriptor": "ensayo", "tastes": ["ensayo", 7, ""]}\n```')

    profile = await _classifier(httpx.MockTransport(handler)).infer(TITLES)
    assert profile is not None
    assert profile.descriptor == "ensayo"
    assert profile.tastes == ("ensayo",)  # 7 and "" dropped


async def test_blank_descriptor_returns_none() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _completion('{"descriptor": "   ", "tastes": ["x"]}')

    assert await _classifier(httpx.MockTransport(handler)).infer(TITLES) is None


async def test_any_failure_returns_none() -> None:
    def http_500(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    def not_json(_request: httpx.Request) -> httpx.Response:
        return _completion("lo siento")

    for handler in (http_500, not_json):
        assert await _classifier(httpx.MockTransport(handler)).infer(TITLES) is None


async def test_no_key_or_empty_shelf_skips_the_call() -> None:
    assert await OpenRouterColdStartClassifier(api_key="", model="m").infer(TITLES) is None
    assert await NullColdStartClassifier().infer(TITLES) is None
