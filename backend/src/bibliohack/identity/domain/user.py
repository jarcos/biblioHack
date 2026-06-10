"""Identity domain — the `User` aggregate and its value objects.

A user is someone with an account: an email (their login), an Argon2id
password hash, and a verified flag (public registration requires proving
ownership of the email before login). The domain layer knows nothing about
hashing algorithms or storage — `PasswordHash` is an opaque encoded string
produced by the `PasswordHasher` port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bibliohack.shared.domain.entity import Entity
from bibliohack.shared.domain.identifier import Identifier
from bibliohack.shared.domain.value_object import ValueObject

if TYPE_CHECKING:
    from typing import Self

# Conservative shape check only — real validation is the verification mail.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_EMAIL_MAX_LENGTH = 254  # RFC 5321 path limit


class UserId(Identifier):
    """Strongly-typed user identifier."""


@dataclass(frozen=True, slots=True)
class Email(ValueObject):
    """A normalized (lowercased, stripped) email address.

    Raises `ValueError` on malformed input — constructing an invalid Email is
    a bug; use cases catch it at the boundary and turn it into an `Err`.
    """

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if len(normalized) > _EMAIL_MAX_LENGTH or not _EMAIL_RE.match(normalized):
            msg = "malformed email address"
            raise ValueError(msg)
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PasswordHash(ValueObject):
    """Opaque encoded password hash (Argon2id encoded string, salt included).

    The domain never sees plaintext passwords — hashing happens behind the
    `PasswordHasher` port and only the encoded result crosses into here.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            msg = "password hash must not be empty"
            raise ValueError(msg)


class User(Entity[UserId]):
    """Aggregate root for an account holder."""

    def __init__(
        self,
        *,
        user_id: UserId,
        email: Email,
        password_hash: PasswordHash,
        email_verified: bool = False,
        display_name: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__(user_id)
        self._email = email
        self._password_hash = password_hash
        self._email_verified = email_verified
        self._display_name = display_name
        self._created_at = created_at if created_at is not None else datetime.now(UTC)

    @classmethod
    def register(
        cls,
        *,
        email: Email,
        password_hash: PasswordHash,
        display_name: str | None = None,
    ) -> Self:
        """A freshly registered user: new id, email not yet verified."""
        return cls(
            user_id=UserId.new(),
            email=email,
            password_hash=password_hash,
            email_verified=False,
            display_name=display_name,
        )

    @property
    def email(self) -> Email:
        return self._email

    @property
    def password_hash(self) -> PasswordHash:
        return self._password_hash

    @property
    def email_verified(self) -> bool:
        return self._email_verified

    @property
    def display_name(self) -> str | None:
        return self._display_name

    @property
    def created_at(self) -> datetime:
        return self._created_at

    def mark_email_verified(self) -> None:
        """Email-ownership proven (verification token consumed). Idempotent."""
        self._email_verified = True

    def change_password(self, new_hash: PasswordHash) -> None:
        self._password_hash = new_hash
