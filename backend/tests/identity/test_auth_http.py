"""HTTP tests for /api/auth/* — the real app with in-memory fakes behind
the provider dependencies. No database, no Redis: the providers are
overridden, so `get_tx_session` never resolves.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from bibliohack.identity.interfaces.http.dependencies import (
    get_captcha_verifier,
    get_mailer,
    get_password_hasher,
    get_session_store,
    get_token_service,
    get_user_repository,
)
from bibliohack.identity.interfaces.http.router import get_register_branch_follows
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import get_rate_limiter
from bibliohack.shared.infrastructure.settings import get_settings
from tests.identity.fakes import (
    AlwaysFailCaptcha,
    AlwaysPassCaptcha,
    FakePasswordHasher,
    InMemorySessionStore,
    InMemoryTokenService,
    InMemoryUserRepository,
    RecordingMailer,
)
from tests.shared.fakes import AllowAllRateLimiter

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI


class FakeBranchFollows:
    """In-memory stand-in for the register endpoint's branch-follow writer (L5)."""

    def __init__(self, known: tuple[str, ...] = ("HU0001", "SE0001")) -> None:
        self.known = set(known)
        self.saved: dict[str, list[str]] = {}

    async def existing_codes(self, codes: object) -> set[str]:
        return {c for c in codes if c in self.known}  # type: ignore[union-attr]

    async def set_followed(self, user_id: str, codes: object) -> None:
        self.saved[user_id] = list(codes)  # type: ignore[arg-type]


@pytest.fixture
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture
def follows() -> FakeBranchFollows:
    return FakeBranchFollows()


@pytest.fixture
def auth_app(mailer: RecordingMailer, follows: FakeBranchFollows) -> FastAPI:
    app = create_app()
    users = InMemoryUserRepository()
    sessions = InMemorySessionStore()
    tokens = InMemoryTokenService()
    app.dependency_overrides[get_user_repository] = lambda: users
    app.dependency_overrides[get_session_store] = lambda: sessions
    app.dependency_overrides[get_token_service] = lambda: tokens
    app.dependency_overrides[get_mailer] = lambda: mailer
    app.dependency_overrides[get_password_hasher] = FakePasswordHasher
    app.dependency_overrides[get_captcha_verifier] = AlwaysPassCaptcha
    app.dependency_overrides[get_rate_limiter] = AllowAllRateLimiter
    app.dependency_overrides[get_register_branch_follows] = lambda: follows
    return app


@pytest.fixture
def client(auth_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(auth_app) as test_client:
        yield test_client


def _register(client: TestClient, email: str = "jose@example.com") -> None:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "long-enough-pass", "display_name": "José"},
    )
    assert response.status_code == 201, response.text


def _extract_token(mailer: RecordingMailer) -> str:
    match = re.search(r"token=([\w.~-]+)", mailer.sent[-1][2])
    assert match is not None
    return match.group(1)


def test_full_flow_register_verify_login_me_logout(
    client: TestClient, mailer: RecordingMailer
) -> None:
    _register(client)

    # Login before verifying: blocked (public registration requires proof).
    blocked = client.post(
        "/api/auth/login", json={"email": "jose@example.com", "password": "long-enough-pass"}
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "email_not_verified"

    # Verify with the mailed token.
    assert (
        client.post("/api/auth/verify", json={"token": _extract_token(mailer)}).status_code == 204
    )

    # Login sets the session cookie.
    logged_in = client.post(
        "/api/auth/login", json={"email": "JOSE@example.com", "password": "long-enough-pass"}
    )
    assert logged_in.status_code == 200
    body = logged_in.json()
    assert body["email"] == "jose@example.com"
    assert body["email_verified"] is True
    assert get_settings().session_cookie_name in logged_in.cookies

    # /me works with the cookie (TestClient persists it).
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "jose@example.com"

    # Logout kills the session server-side.
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401


def test_register_validation_and_conflicts(client: TestClient) -> None:
    _register(client)
    duplicate = client.post(
        "/api/auth/register",
        json={"email": "jose@example.com", "password": "long-enough-pass"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "email_taken"

    bad_email = client.post(
        "/api/auth/register", json={"email": "nope", "password": "long-enough-pass"}
    )
    assert bad_email.status_code == 422

    # Short password is caught by the schema before the use case runs.
    weak = client.post("/api/auth/register", json={"email": "b@example.com", "password": "short"})
    assert weak.status_code == 422


def test_register_with_branch_codes_follows_them(
    client: TestClient, follows: FakeBranchFollows
) -> None:
    """L5: valid picked libraries are followed for the new account."""
    response = client.post(
        "/api/auth/register",
        json={
            "email": "picker@example.com",
            "password": "long-enough-pass",
            "branch_codes": ["HU0001", "SE0001"],
        },
    )
    assert response.status_code == 201, response.text
    assert list(follows.saved.values()) == [["HU0001", "SE0001"]]


def test_register_without_branch_codes_sets_no_follows(
    client: TestClient, follows: FakeBranchFollows
) -> None:
    """Omitting the picker (the skip path) follows nothing."""
    _register(client)
    assert follows.saved == {}


def test_register_with_unknown_branch_code_is_422_before_any_account(
    client: TestClient, mailer: RecordingMailer, follows: FakeBranchFollows
) -> None:
    """An unknown code is rejected up front — no follow set, no account, no mail."""
    bad = client.post(
        "/api/auth/register",
        json={
            "email": "picker@example.com",
            "password": "long-enough-pass",
            "branch_codes": ["HU0001", "NOPE9999"],
        },
    )
    assert bad.status_code == 422
    assert "NOPE9999" in bad.json()["detail"]
    assert follows.saved == {}
    assert mailer.sent == []  # validated before RegisterUser, so no verification mail
    # And the email is still free — the account was never created.
    ok = client.post(
        "/api/auth/register",
        json={"email": "picker@example.com", "password": "long-enough-pass"},
    )
    assert ok.status_code == 201


def test_login_with_bad_credentials_is_401(client: TestClient, mailer: RecordingMailer) -> None:
    _register(client)
    client.post("/api/auth/verify", json={"token": _extract_token(mailer)})

    wrong = client.post(
        "/api/auth/login", json={"email": "jose@example.com", "password": "wrong-password"}
    )
    unknown = client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "wrong-password"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # indistinguishable


def test_me_without_cookie_is_401(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_password_reset_flow_revokes_sessions(client: TestClient, mailer: RecordingMailer) -> None:
    _register(client)
    client.post("/api/auth/verify", json={"token": _extract_token(mailer)})
    client.post(
        "/api/auth/login", json={"email": "jose@example.com", "password": "long-enough-pass"}
    )
    assert client.get("/api/auth/me").status_code == 200

    # Request a reset (always 202, even for ghosts) and redeem the token.
    assert (
        client.post(
            "/api/auth/password/reset-request", json={"email": "ghost@example.com"}
        ).status_code
        == 202
    )
    assert (
        client.post(
            "/api/auth/password/reset-request", json={"email": "jose@example.com"}
        ).status_code
        == 202
    )
    reset = client.post(
        "/api/auth/password/reset",
        json={"token": _extract_token(mailer), "new_password": "a-new-long-password"},
    )
    assert reset.status_code == 204

    # The old session died with the reset.
    assert client.get("/api/auth/me").status_code == 401

    # And the new password works.
    relogin = client.post(
        "/api/auth/login", json={"email": "jose@example.com", "password": "a-new-long-password"}
    )
    assert relogin.status_code == 200


def test_failed_captcha_blocks_register_and_login(auth_app: FastAPI) -> None:
    auth_app.dependency_overrides[get_captcha_verifier] = AlwaysFailCaptcha
    with TestClient(auth_app) as client:
        register = client.post(
            "/api/auth/register",
            json={"email": "a@example.com", "password": "long-enough-pass"},
        )
        login = client.post(
            "/api/auth/login", json={"email": "a@example.com", "password": "long-enough-pass"}
        )
    assert register.status_code == 400
    assert login.status_code == 400
