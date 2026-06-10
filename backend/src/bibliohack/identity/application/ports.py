"""Ports for the identity context.

Use cases depend on these abstractions; concrete adapters live under
`identity/infrastructure/`. Tests substitute in-memory fakes. Identifiers
cross the boundary as plain strings (UUIDs), matching the port discipline of
the other contexts — except the `User` aggregate itself, which stays a domain
object on both sides of `UserRepository` (same-context traffic).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from bibliohack.identity.domain.user import User


class TokenPurpose(StrEnum):
    """What a one-time token proves. Issued and consumed strictly per purpose."""

    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"  # noqa: S105 — token purpose, not a credential


class UserRepository(Protocol):
    """Persistence for the `User` aggregate."""

    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_id(self, user_id: str) -> User | None: ...

    async def add(self, user: User) -> None:
        """Persist a new user. Email uniqueness is enforced by the database."""
        ...

    async def set_email_verified(self, user_id: str) -> None: ...

    async def update_password_hash(self, user_id: str, password_hash: str) -> None: ...


class PasswordHasher(Protocol):
    """The `AuthProvider` of ARCHITECTURE.md §4 — local password auth."""

    def hash(self, plain: str) -> str: ...

    def verify(self, plain: str, hashed: str) -> bool:
        """True iff `plain` matches `hashed`. Never raises on malformed hashes."""
        ...

    def needs_rehash(self, hashed: str) -> bool:
        """True when `hashed` predates the current parameters (rehash on login)."""
        ...


class SessionStore(Protocol):
    """Server-side sessions: opaque id → user id, with a TTL."""

    async def create(self, user_id: str) -> str:
        """Create a session and return its opaque id (goes into the cookie)."""
        ...

    async def get(self, session_id: str) -> str | None:
        """The session's user id, or None when missing/expired."""
        ...

    async def delete(self, session_id: str) -> None: ...

    async def delete_for_user(self, user_id: str) -> None:
        """Revoke every session of a user (password reset, account deletion)."""
        ...


class TokenService(Protocol):
    """One-time, expiring, purpose-bound tokens (email verification / reset)."""

    async def issue(self, user_id: str, purpose: TokenPurpose) -> str:
        """Create a token for the user and return the *raw* token (mailed once)."""
        ...

    async def consume(self, token: str, purpose: TokenPurpose) -> str | None:
        """Redeem a raw token: its user id, or None if unknown/expired/used."""
        ...


class Mailer(Protocol):
    """Outbound transactional mail (NAS SMTP in production, recorder in tests)."""

    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class CaptchaVerifier(Protocol):
    """Bot protection on register/login (Cloudflare Turnstile in production)."""

    async def verify(self, token: str | None, remote_ip: str | None = None) -> bool: ...
