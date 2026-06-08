"""Unit test for the cover serving route.

Builds a tiny app with just the covers router (no DB), points the store at a
tmp dir, and checks: a stored cover streams back as WebP with an immutable
cache header; a missing one 404s; a non-sha path 404s (and never reaches the
store — path-traversal guard).
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bibliohack.covers.interfaces.http.router import router as covers_router

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def covers_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("COVERS_STORE_PATH", str(tmp_path))
    from bibliohack.shared.infrastructure.settings import get_settings

    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(covers_router)
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _store_cover(root: Path, data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    (root / sha[:2]).mkdir(parents=True, exist_ok=True)
    (root / sha[:2] / f"{sha}.webp").write_bytes(data)
    return sha


def test_serves_stored_cover_as_immutable_webp(covers_client: TestClient, tmp_path: Path) -> None:
    sha = _store_cover(tmp_path, b"RIFF....WEBPfake")
    resp = covers_client.get(f"/catalog/covers/{sha}.webp")
    assert resp.status_code == 200
    assert resp.content == b"RIFF....WEBPfake"
    assert resp.headers["content-type"] == "image/webp"
    assert "immutable" in resp.headers["cache-control"]


def test_missing_cover_is_404(covers_client: TestClient) -> None:
    sha = hashlib.sha256(b"absent").hexdigest()
    assert covers_client.get(f"/catalog/covers/{sha}.webp").status_code == 404


def test_non_sha_path_is_404(covers_client: TestClient) -> None:
    # Not 64 hex chars → rejected before touching the store.
    assert covers_client.get("/catalog/covers/not-a-sha.webp").status_code == 404
