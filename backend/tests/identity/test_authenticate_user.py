"""AuthenticateUser use-case tests (in-memory fakes)."""

from __future__ import annotations

import pytest

from bibliohack.identity.application.errors import LoginError
from bibliohack.identity.application.use_cases.authenticate_user import AuthenticateUser
from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.shared.application.result import Err, Ok
from tests.identity.fakes import (
    FakePasswordHasher,
    InMemorySessionStore,
    InMemoryUserRepository,
)


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def sessions() -> InMemorySessionStore:
    return InMemorySessionStore()


async def _add_user(
    users: InMemoryUserRepository, *, email: str = "a@example.com", verified: bool = True
) -> User:
    user = User.register(
        email=Email(email), password_hash=PasswordHash("fakehash:correct-password")
    )
    if verified:
        user.mark_email_verified()
    await users.add(user)
    return user


async def test_valid_credentials_open_a_session(
    users: InMemoryUserRepository, sessions: InMemorySessionStore
) -> None:
    user = await _add_user(users)
    result = await AuthenticateUser(
        users=users, hasher=FakePasswordHasher(), sessions=sessions
    ).execute(email="A@example.com ", password="correct-password")

    assert isinstance(result, Ok)
    assert result.value.user == user
    assert sessions.sessions[result.value.session_id] == str(user.id)


async def test_wrong_password_and_unknown_email_look_identical(
    users: InMemoryUserRepository, sessions: InMemorySessionStore
) -> None:
    await _add_user(users)
    use_case = AuthenticateUser(users=users, hasher=FakePasswordHasher(), sessions=sessions)

    wrong = await use_case.execute(email="a@example.com", password="nope")
    unknown = await use_case.execute(email="ghost@example.com", password="nope")

    assert wrong == Err(LoginError.INVALID_CREDENTIALS)
    assert unknown == Err(LoginError.INVALID_CREDENTIALS)
    assert sessions.sessions == {}


async def test_unknown_email_still_burns_a_hash_for_timing_parity(
    users: InMemoryUserRepository, sessions: InMemorySessionStore
) -> None:
    hasher = FakePasswordHasher()
    await AuthenticateUser(users=users, hasher=hasher, sessions=sessions).execute(
        email="ghost@example.com", password="whatever"
    )
    assert hasher.hash_calls == 1


async def test_unverified_email_blocks_login_when_required(
    users: InMemoryUserRepository, sessions: InMemorySessionStore
) -> None:
    await _add_user(users, verified=False)
    result = await AuthenticateUser(
        users=users, hasher=FakePasswordHasher(), sessions=sessions
    ).execute(email="a@example.com", password="correct-password")
    assert result == Err(LoginError.EMAIL_NOT_VERIFIED)


async def test_unverified_email_allowed_when_not_required(
    users: InMemoryUserRepository, sessions: InMemorySessionStore
) -> None:
    await _add_user(users, verified=False)
    result = await AuthenticateUser(
        users=users,
        hasher=FakePasswordHasher(),
        sessions=sessions,
        require_verified_email=False,
    ).execute(email="a@example.com", password="correct-password")
    assert isinstance(result, Ok)


async def test_login_rehashes_when_parameters_are_stale(
    users: InMemoryUserRepository, sessions: InMemorySessionStore
) -> None:
    user = await _add_user(users)
    hasher = FakePasswordHasher(needs_rehash=True)
    result = await AuthenticateUser(users=users, hasher=hasher, sessions=sessions).execute(
        email="a@example.com", password="correct-password"
    )
    assert isinstance(result, Ok)
    refreshed = await users.get_by_id(str(user.id))
    assert refreshed is not None
    assert refreshed.password_hash.value == "fakehash:correct-password"
    assert hasher.hash_calls == 1  # the rehash
