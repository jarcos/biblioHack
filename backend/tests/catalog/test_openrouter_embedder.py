"""Unit tests for the OpenRouter BGE-M3 embedder (HTTP mocked with respx)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from bibliohack.catalog.infrastructure.embeddings.openrouter import OpenRouterEmbedder

_BASE = "https://openrouter.example/api/v1"
_EP = f"{_BASE}/embeddings"


def _embedder(model: str = "baai/bge-m3") -> OpenRouterEmbedder:
    return OpenRouterEmbedder(api_key="tok", base_url=_BASE, model=model)


def _payload(*vectors: list[float], shuffled: bool = False) -> dict[str, object]:
    data = [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)]
    if shuffled:
        data.reverse()
    return {"object": "list", "data": data, "model": "baai/bge-m3"}


def test_reports_the_bge_m3_dimension() -> None:
    assert _embedder().dimensions == 1024


@respx.mock
def test_vectors_come_back_l2_normalized_in_input_order() -> None:
    respx.post(_EP).mock(
        return_value=httpx.Response(200, json=_payload([3.0, 4.0], [0.0, 5.0], shuffled=True))
    )

    out = _embedder().embed_documents(["a", "b"])

    assert out[0] == pytest.approx([0.6, 0.8])
    assert out[1] == pytest.approx([0.0, 1.0])


@respx.mock
def test_sends_the_model_the_inputs_and_the_bearer_key() -> None:
    route = respx.post(_EP).mock(return_value=httpx.Response(200, json=_payload([1.0, 0.0])))

    _embedder(model="baai/bge-m3").embed_query("hola")

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer tok"
    assert json.loads(request.content) == {"model": "baai/bge-m3", "input": ["hola"]}


@respx.mock
def test_a_trailing_slash_on_the_base_url_is_harmless() -> None:
    route = respx.post(_EP).mock(return_value=httpx.Response(200, json=_payload([1.0])))

    OpenRouterEmbedder(api_key="tok", base_url=f"{_BASE}/").embed_query("x")

    assert route.called


def test_no_texts_means_no_request() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(_EP)
        assert _embedder().embed_documents([]) == []
        assert not route.called


@respx.mock
def test_http_errors_propagate_for_the_caller_to_handle() -> None:
    respx.post(_EP).mock(return_value=httpx.Response(402, json={"error": "no credits"}))

    with pytest.raises(httpx.HTTPStatusError):
        _embedder().embed_documents(["a"])


@respx.mock
def test_a_short_answer_is_an_error_not_a_misaligned_batch() -> None:
    respx.post(_EP).mock(return_value=httpx.Response(200, json=_payload([1.0, 0.0])))

    with pytest.raises(ValueError, match="2 inputs"):
        _embedder().embed_documents(["a", "b"])


@respx.mock
def test_an_error_body_with_status_200_is_an_error() -> None:
    respx.post(_EP).mock(return_value=httpx.Response(200, json={"error": {"message": "x"}}))

    with pytest.raises(ValueError, match="unexpected"):
        _embedder().embed_query("a")


@respx.mock
def test_a_zero_vector_stays_finite() -> None:
    respx.post(_EP).mock(return_value=httpx.Response(200, json=_payload([0.0, 0.0])))

    assert _embedder().embed_query("a") == [0.0, 0.0]
