"""Smoke tests — the app starts and the health endpoint responds."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack import __version__

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_version_returns_ok(client: TestClient) -> None:
    response = client.get("/version")

    assert response.status_code == 200
    assert response.json()["version"] == __version__


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    body = response.json()
    assert body["info"]["title"] == "biblioHack"
    assert body["info"]["version"] == __version__
