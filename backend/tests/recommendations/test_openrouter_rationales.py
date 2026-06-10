"""OpenRouterRationaleWriter tests — httpx.MockTransport, no network."""

from __future__ import annotations

import json

import httpx

from bibliohack.recommendations.application.ports import Candidate
from bibliohack.recommendations.infrastructure.llm.openrouter_rationales import (
    NullRationaleWriter,
    OpenRouterRationaleWriter,
)

CANDIDATES = (
    Candidate(record_id="rec-1", title="Nada", author="Carmen Laforet", score=0.9),
    Candidate(record_id="rec-2", title="La colmena", author="Cela", score=0.8),
)


def _writer(handler: httpx.MockTransport) -> OpenRouterRationaleWriter:
    return OpenRouterRationaleWriter(
        api_key="test-key",
        model="test/model",
        transport=handler,
    )


def _completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_maps_numbered_answers_back_to_record_ids() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("Authorization")
        return _completion('{"1": "Posguerra íntima.", "2": "Coral y mordaz."}')

    rationales = await _writer(httpx.MockTransport(handler)).write(
        liked_books=("Cien años de soledad — García Márquez",), candidates=CANDIDATES
    )

    assert rationales == {"rec-1": "Posguerra íntima.", "rec-2": "Coral y mordaz."}
    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert "Nada" in body["messages"][1]["content"]


async def test_tolerates_fenced_json_and_partial_answers() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _completion('Aquí tienes:\n```json\n{"2": "Coral y mordaz.", "9": "??"}\n```')

    rationales = await _writer(httpx.MockTransport(handler)).write(
        liked_books=(), candidates=CANDIDATES
    )
    assert rationales == {"rec-2": "Coral y mordaz."}


async def test_any_failure_returns_empty() -> None:
    def http_500(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    def not_json(_request: httpx.Request) -> httpx.Response:
        return _completion("lo siento, no puedo")

    for handler in (http_500, not_json):
        rationales = await _writer(httpx.MockTransport(handler)).write(
            liked_books=(), candidates=CANDIDATES
        )
        assert rationales == {}


async def test_no_key_or_no_candidates_skips_the_call() -> None:
    writer = OpenRouterRationaleWriter(api_key="", model="m")
    assert await writer.write(liked_books=(), candidates=CANDIDATES) == {}

    null_writer = NullRationaleWriter()
    assert await null_writer.write(liked_books=(), candidates=CANDIDATES) == {}
