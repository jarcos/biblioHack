"""HTTP tests for /api/recommendations — fakes behind the providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.identity.interfaces.http.dependencies import get_current_user
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import get_tx_session
from bibliohack.recommendations.application.ports import CandidateBatch, ColdStartProfile
from bibliohack.recommendations.interfaces.http.dependencies import (
    get_caller_branch_codes,
    get_candidate_retriever,
    get_cold_start_classifier,
    get_rationale_writer,
    get_recommendation_repository,
    get_shelf_taste_reader,
)
from tests.recommendations.test_get_recommendations import (
    FakeClassifier,
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


def _app(
    reader: User,
    *,
    fingerprint: str | None,
    raw_shelf: tuple[str, ...] = (),
    classifier_profile: ColdStartProfile | None = None,
) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: reader
    app.dependency_overrides[get_shelf_taste_reader] = lambda: FakeShelf(
        fingerprint, raw_shelf=raw_shelf
    )
    app.dependency_overrides[get_candidate_retriever] = lambda: FakeRetriever(
        CandidateBatch(liked_books=(), candidates=())
    )
    app.dependency_overrides[get_rationale_writer] = FakeRationales
    app.dependency_overrides[get_recommendation_repository] = FakeRepository
    app.dependency_overrides[get_cold_start_classifier] = lambda: FakeClassifier(classifier_profile)
    # Library-aware resolution is a dependency so it overrides without a DB.
    app.dependency_overrides[get_caller_branch_codes] = lambda: None
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
    assert response.json() == {
        "reason": "empty_profile",
        "cold_start": False,
        "inferred_tastes": [],
        "items": [],
    }


def test_ok_with_empty_batch(reader: User) -> None:
    with TestClient(_app(reader, fingerprint="fp-1")) as client:
        response = client.get("/api/recommendations")
    assert response.status_code == 200
    assert response.json() == {
        "reason": "ok",
        "cold_start": False,
        "inferred_tastes": [],
        "items": [],
    }


def test_cold_start_surfaces_flag_and_tastes(reader: User) -> None:
    """No matched books but a non-empty raw shelf + a classifier read → the
    response is flagged cold_start with the inferred tastes (empty retrieval
    keeps this DB-free)."""
    app = _app(
        reader,
        fingerprint=None,
        raw_shelf=("Patria — Aramburu",),
        classifier_profile=ColdStartProfile(
            descriptor="novela histórica española", tastes=("novela histórica", "guerra civil")
        ),
    )
    with TestClient(app) as client:
        response = client.get("/api/recommendations")
    assert response.status_code == 200
    assert response.json() == {
        "reason": "ok",
        "cold_start": True,
        "inferred_tastes": ["novela histórica", "guerra civil"],
        "items": [],
    }
