"""Domain tests — Email/PasswordHash value objects, User transitions."""

from __future__ import annotations

import pytest

from bibliohack.identity.domain.user import Email, PasswordHash, User


class TestEmail:
    def test_normalizes_case_and_whitespace(self) -> None:
        assert Email("  Jose.Arcos@FeverUp.com ").value == "jose.arcos@feverup.com"

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "not-an-email",
            "missing@tld",
            "two@@signs.example",
            "spaces in@local.example",
            "a" * 250 + "@example.com",  # over the RFC length cap
        ],
    )
    def test_rejects_malformed(self, raw: str) -> None:
        with pytest.raises(ValueError, match="malformed email"):
            Email(raw)

    def test_value_equality(self) -> None:
        assert Email("a@example.com") == Email("A@example.com")


class TestPasswordHash:
    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            PasswordHash("")


class TestUser:
    def test_register_starts_unverified_with_fresh_id(self) -> None:
        a = User.register(email=Email("a@example.com"), password_hash=PasswordHash("h"))
        b = User.register(email=Email("a@example.com"), password_hash=PasswordHash("h"))
        assert not a.email_verified
        assert a.id != b.id

    def test_mark_email_verified_is_idempotent(self) -> None:
        user = User.register(email=Email("a@example.com"), password_hash=PasswordHash("h"))
        user.mark_email_verified()
        user.mark_email_verified()
        assert user.email_verified

    def test_change_password_swaps_the_hash(self) -> None:
        user = User.register(email=Email("a@example.com"), password_hash=PasswordHash("old"))
        user.change_password(PasswordHash("new"))
        assert user.password_hash.value == "new"
