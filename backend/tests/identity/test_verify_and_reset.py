"""VerifyEmail, RequestPasswordReset and ResetPassword use-case tests."""

from __future__ import annotations

import pytest

from bibliohack.identity.application.errors import ResetPasswordError, TokenError
from bibliohack.identity.application.ports import TokenPurpose
from bibliohack.identity.application.use_cases.request_password_reset import RequestPasswordReset
from bibliohack.identity.application.use_cases.reset_password import ResetPassword
from bibliohack.identity.application.use_cases.verify_email import VerifyEmail
from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.shared.application.result import Err, Ok
from tests.identity.fakes import (
    FakePasswordHasher,
    InMemorySessionStore,
    InMemoryTokenService,
    InMemoryUserRepository,
    RecordingMailer,
)


@pytest.fixture
def users() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def tokens() -> InMemoryTokenService:
    return InMemoryTokenService()


async def _add_user(users: InMemoryUserRepository) -> User:
    user = User.register(email=Email("a@example.com"), password_hash=PasswordHash("fakehash:old"))
    await users.add(user)
    return user


class TestVerifyEmail:
    async def test_valid_token_flips_the_flag_and_is_single_use(
        self, users: InMemoryUserRepository, tokens: InMemoryTokenService
    ) -> None:
        user = await _add_user(users)
        token = await tokens.issue(str(user.id), TokenPurpose.EMAIL_VERIFICATION)
        use_case = VerifyEmail(users=users, tokens=tokens)

        assert await use_case.execute(token) == Ok(None)
        assert user.email_verified
        assert await use_case.execute(token) == Err(TokenError.INVALID_OR_EXPIRED)

    async def test_wrong_purpose_token_is_rejected(
        self, users: InMemoryUserRepository, tokens: InMemoryTokenService
    ) -> None:
        user = await _add_user(users)
        reset_token = await tokens.issue(str(user.id), TokenPurpose.PASSWORD_RESET)
        result = await VerifyEmail(users=users, tokens=tokens).execute(reset_token)
        assert result == Err(TokenError.INVALID_OR_EXPIRED)
        assert not user.email_verified


class TestRequestPasswordReset:
    async def test_known_email_gets_a_mail_with_the_link(
        self, users: InMemoryUserRepository, tokens: InMemoryTokenService
    ) -> None:
        await _add_user(users)
        mailer = RecordingMailer()
        await RequestPasswordReset(
            users=users, tokens=tokens, mailer=mailer, public_base_url="https://biblio.example/"
        ).execute(email="A@EXAMPLE.COM")

        assert len(mailer.sent) == 1
        _to, _subject, body = mailer.sent[0]
        assert "https://biblio.example/reset-password?token=tok-password_reset-1" in body

    async def test_unknown_email_sends_nothing_and_says_nothing(
        self, users: InMemoryUserRepository, tokens: InMemoryTokenService
    ) -> None:
        mailer = RecordingMailer()
        await RequestPasswordReset(
            users=users, tokens=tokens, mailer=mailer, public_base_url="https://biblio.example"
        ).execute(email="ghost@example.com")
        assert mailer.sent == []
        assert tokens.tokens == {}


class TestResetPassword:
    async def test_valid_token_sets_hash_and_revokes_all_sessions(
        self, users: InMemoryUserRepository, tokens: InMemoryTokenService
    ) -> None:
        user = await _add_user(users)
        sessions = InMemorySessionStore()
        await sessions.create(str(user.id))
        await sessions.create(str(user.id))
        token = await tokens.issue(str(user.id), TokenPurpose.PASSWORD_RESET)

        result = await ResetPassword(
            users=users, hasher=FakePasswordHasher(), tokens=tokens, sessions=sessions
        ).execute(token=token, new_password="brand-new-password")

        assert result == Ok(None)
        assert user.password_hash.value == "fakehash:brand-new-password"
        assert sessions.sessions == {}

    async def test_weak_password_does_not_burn_the_token(
        self, users: InMemoryUserRepository, tokens: InMemoryTokenService
    ) -> None:
        user = await _add_user(users)
        sessions = InMemorySessionStore()
        token = await tokens.issue(str(user.id), TokenPurpose.PASSWORD_RESET)
        use_case = ResetPassword(
            users=users, hasher=FakePasswordHasher(), tokens=tokens, sessions=sessions
        )

        assert await use_case.execute(token=token, new_password="short") == Err(
            ResetPasswordError.WEAK_PASSWORD
        )
        # The token survived the weak attempt and still works:
        assert await use_case.execute(token=token, new_password="brand-new-password") == Ok(None)

    async def test_invalid_token_is_rejected(
        self, users: InMemoryUserRepository, tokens: InMemoryTokenService
    ) -> None:
        result = await ResetPassword(
            users=users,
            hasher=FakePasswordHasher(),
            tokens=tokens,
            sessions=InMemorySessionStore(),
        ).execute(token="bogus", new_password="brand-new-password")
        assert result == Err(ResetPasswordError.INVALID_OR_EXPIRED)
