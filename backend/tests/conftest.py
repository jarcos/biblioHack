"""Pytest fixtures shared across the test suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from bibliohack.interfaces.http.app import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI


@pytest.fixture
def app() -> FastAPI:
    """A fresh FastAPI app per test. Avoids accidental cross-test state."""
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Synchronous test client. Async-needing tests use httpx.AsyncClient directly."""
    with TestClient(app) as test_client:
        yield test_client
