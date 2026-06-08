"""Unit tests for the HuggingFace BGE-M3 embedder (HTTP mocked with respx)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from bibliohack.catalog.infrastructure.embeddings.huggingface import HuggingFaceEmbedder

_EP = "https://api-inference.huggingface.co/models/BAAI/bge-m3"


@respx.mock
def test_pooled_vectors_are_l2_normalized() -> None:
    respx.post(_EP).mock(return_value=httpx.Response(200, json=[[3.0, 4.0], [0.0, 5.0]]))
    out = HuggingFaceEmbedder(api_token="x", endpoint=_EP).embed_documents(["a", "b"])
    assert out[0] == pytest.approx([0.6, 0.8])  # [3,4] / 5
    assert out[1] == pytest.approx([0.0, 1.0])  # [0,5] / 5


@respx.mock
def test_token_level_output_is_mean_pooled() -> None:
    # One input returned token-level: [[2,0],[0,0]] → mean [1,0] → normalized [1,0].
    respx.post(_EP).mock(return_value=httpx.Response(200, json=[[[2.0, 0.0], [0.0, 0.0]]]))
    assert HuggingFaceEmbedder(api_token="x", endpoint=_EP).embed_query("q") == pytest.approx(
        [1.0, 0.0]
    )


@respx.mock
def test_sends_bearer_token_and_inputs() -> None:
    route = respx.post(_EP).mock(return_value=httpx.Response(200, json=[[1.0, 0.0]]))
    HuggingFaceEmbedder(api_token="tok", endpoint=_EP).embed_query("hola")
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer tok"
    body = json.loads(request.content)
    assert body["inputs"] == ["hola"]
    assert body["options"]["wait_for_model"] is True
