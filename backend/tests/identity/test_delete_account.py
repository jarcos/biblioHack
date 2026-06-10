"""DeleteAccount use-case tests (in-memory fakes)."""

from __future__ import annotations

from bibliohack.identity.application.use_cases.delete_account import (
    DeleteAccount,
    DeleteAccountError,
)
from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.shared.application.result import Err, Ok
from tests.identity.fakes import (
    FakePasswordHasher,
    InMemorySessionStore,
    InMemoryUserRepository,
)


async def _setup() -> tuple[InMemoryUserRepository, InMemorySessionStore, str]:
    users = InMemoryUserRepository()
    sessions = InMemorySessionStore()
    user = User.register(
        email=Email("a@example.com"), password_hash=PasswordHash("fakehash:right-password")
    )
    await users.add(user)
    await sessions.create(str(user.id))
    await sessions.create(str(user.id))
    return users, sessions, str(user.id)


async def test_correct_password_erases_user_and_sessions() -> None:
    users, sessions, user_id = await _setup()
    result = await DeleteAccount(
        users=users, hasher=FakePasswordHasher(), sessions=sessions
    ).execute(user_id=user_id, password="right-password")

    assert result == Ok(None)
    assert users.users == {}
    assert sessions.sessions == {}


async def test_wrong_password_changes_nothing() -> None:
    users, sessions, user_id = await _setup()
    result = await DeleteAccount(
        users=users, hasher=FakePasswordHasher(), sessions=sessions
    ).execute(user_id=user_id, password="wrong")

    assert result == Err(DeleteAccountError.INVALID_PASSWORD)
    assert user_id in users.users
    assert len(sessions.sessions) == 2


async def test_missing_user_reports_invalid_password() -> None:
    users, sessions, _user_id = await _setup()
    result = await DeleteAccount(
        users=users, hasher=FakePasswordHasher(), sessions=sessions
    ).execute(user_id="ghost", password="whatever")
    assert result == Err(DeleteAccountError.INVALID_PASSWORD)
