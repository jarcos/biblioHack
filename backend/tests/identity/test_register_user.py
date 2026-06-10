"""RegisterUser use-case tests (in-memory fakes)."""

from __future__ import annotations

import pytest

from bibliohack.identity.application.errors import RegisterError
from bibliohack.identity.application.use_cases.register_user import RegisterUser
from bibliohack.shared.application.result import Err, Ok
from tests.identity.fakes import (
    FakePasswordHasher,
    InMemoryTokenService,
    InMemoryUserRepository,
    RecordingMailer,
)


def _use_case(
    users: InMemoryUserRepository,
    mailer: RecordingMailer,
    tokens: InMemoryTokenService,
    *,
    enabled: bool = True,
) -> RegisterUser:
    return RegisterUser(
        users=users,
        hasher=FakePasswordHasher(),
        tokens=tokens,
        mailer=mailer,
        registration_enabled=enabled,
        public_base_url="https://biblio.example",
    )


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture
def tokens() -> InMemoryTokenService:
    return InMemoryTokenService()


async def test_happy_path_creates_unverified_user_and_mails_link(
    users: InMemoryUserRepository, mailer: RecordingMailer, tokens: InMemoryTokenService
) -> None:
    result = await _use_case(users, mailer, tokens).execute(
        email="Jose@Example.com", password="s3cret-enough", display_name="José"
    )

    assert isinstance(result, Ok)
    user = await users.get_by_id(result.value)
    assert user is not None
    assert user.email.value == "jose@example.com"  # normalized
    assert not user.email_verified
    assert user.password_hash.value == "fakehash:s3cret-enough"

    assert len(mailer.sent) == 1
    to, _subject, body = mailer.sent[0]
    assert to == "jose@example.com"
    assert "https://biblio.example/verify?token=tok-email_verification-1" in body


async def test_duplicate_email_is_rejected_case_insensitively(
    users: InMemoryUserRepository, mailer: RecordingMailer, tokens: InMemoryTokenService
) -> None:
    use_case = _use_case(users, mailer, tokens)
    await use_case.execute(email="jose@example.com", password="s3cret-enough")
    result = await use_case.execute(email="JOSE@example.com", password="other-password")

    assert result == Err(RegisterError.EMAIL_TAKEN)
    assert len(mailer.sent) == 1  # only the first registration mailed


async def test_invalid_email_and_weak_password_are_rejected(
    users: InMemoryUserRepository, mailer: RecordingMailer, tokens: InMemoryTokenService
) -> None:
    use_case = _use_case(users, mailer, tokens)
    assert await use_case.execute(email="nope", password="s3cret-enough") == Err(
        RegisterError.INVALID_EMAIL
    )
    assert await use_case.execute(email="a@example.com", password="short") == Err(
        RegisterError.WEAK_PASSWORD
    )
    assert users.users == {}
    assert mailer.sent == []


async def test_kill_switch_blocks_everything(
    users: InMemoryUserRepository, mailer: RecordingMailer, tokens: InMemoryTokenService
) -> None:
    result = await _use_case(users, mailer, tokens, enabled=False).execute(
        email="a@example.com", password="s3cret-enough"
    )
    assert result == Err(RegisterError.REGISTRATION_DISABLED)
    assert users.users == {}
