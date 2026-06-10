"""HTTP tests for /api/recommendations — fakes behind the providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.interfaces.http.dependencies import get_current_user
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import get_tx_session
from bibliohack.recommendations.application.ports import CandidateBatch
from bibliohack.recommendations.interfaces.http.dependencies import (
    get_candidate_retriever,
    get_rationale_writer,
    get_recommendation_repository,
    get_shelf_taste_reader,
)
from tests.recommendations.test_get_recommendations import (
    FakeRationales,
    FakeRepository,
    FakeRetriever,
    FakeShelf,
)

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest.fixture
def reader() -> User:
    return User.register(email=Email("reader@example.com"), password_hash=PasswordHash("h"))


def _app(reader: User, *, fingerprint: str | None) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: reader
    app.dependency_overrides[get_shelf_taste_reader] = lambda: FakeShelf(fingerprint)
    app.dependency_overrides[get_candidate_retriever] = lambda: FakeRetriever(
        CandidateBatch(liked_books=(), candidates=())
    )
    app.dependency_overrides[get_rationale_writer] = FakeRationales
    app.dependency_overrides[get_recommendation_repository] = FakeRepository
    # The route declares a raw session for enrichment; with an empty batch it
    # is never touched, so a stub keeps these tests DB-free.
    app.dependency_overrides[get_tx_session] = lambda: None
    return app


def test_requires_authentication() -> None:
    with TestClient(create_app()) as client:
        assert client.get("/api/recommendations").status_code == 401


def test_empty_profile_reason(reader: User) -> None:
    with TestClient(_app(reader, fingerprint=None)) as client:
        response = client.get("/api/recommendations")
    assert response.status_code == 200
    assert response.json() == {"reason": "empty_profile", "items": []}


def test_ok_with_empty_batch(reader: User) -> None:
    with TestClient(_app(reader, fingerprint="fp-1")) as client:
        response = client.get("/api/recommendations")
    assert response.status_code == 200
    assert response.json() == {"reason": "ok", "items": []}
