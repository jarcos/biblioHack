"""Expected business failures of the identity use cases.

Returned via `Err` (see shared/application/result.py) — never raised. The
HTTP layer maps each value onto a status code.
"""

from __future__ import annotations

from enum import StrEnum

# Single knob for the password policy, shared by register + reset.
MIN_PASSWORD_LENGTH = 8


class RegisterError(StrEnum):
    REGISTRATION_DISABLED = "registration_disabled"
    INVALID_EMAIL = "invalid_email"
    WEAK_PASSWORD = "weak_password"  # noqa: S105 — error code, not a credential
    EMAIL_TAKEN = "email_taken"


class LoginError(StrEnum):
    INVALID_CREDENTIALS = "invalid_credentials"
    EMAIL_NOT_VERIFIED = "email_not_verified"


class TokenError(StrEnum):
    INVALID_OR_EXPIRED = "invalid_or_expired"


class ResetPasswordError(StrEnum):
    INVALID_OR_EXPIRED = "invalid_or_expired"
    WEAK_PASSWORD = "weak_password"  # noqa: S105 — error code, not a credential


def is_acceptable_password(plain: str) -> bool:
    """Minimal sanity floor — length only.

    Composition rules (digits, symbols, …) demonstrably push users toward
    *worse* passwords; length is the one requirement worth enforcing.
    """
    return len(plain) >= MIN_PASSWORD_LENGTH
