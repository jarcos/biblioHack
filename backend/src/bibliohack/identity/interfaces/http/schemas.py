"""Pydantic request/response schemas for the auth API."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — pydantic resolves at model-build time

from pydantic import BaseModel, Field

from bibliohack.identity.application.errors import MIN_PASSWORD_LENGTH


class RegisterRequestSchema(BaseModel):
    """Sign-up payload. Email shape + password policy re-checked in the use case."""

    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=1024)
    display_name: str | None = Field(None, max_length=120)
    turnstile_token: str | None = Field(
        None, description="Cloudflare Turnstile response token; required when enabled."
    )
    branch_codes: list[str] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "Optional RBPA branch codes to follow from the start (L5 — the «Mis "
            "bibliotecas» picker at signup). Empty = none chosen; editable later "
            "on /account. Unknown codes are rejected (422)."
        ),
    )


class LoginRequestSchema(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=1024)
    turnstile_token: str | None = None


class VerifyEmailRequestSchema(BaseModel):
    token: str = Field(..., max_length=128)


class PasswordResetRequestSchema(BaseModel):
    email: str = Field(..., max_length=254)


class PasswordResetSchema(BaseModel):
    token: str = Field(..., max_length=128)
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=1024)


class UserSchema(BaseModel):
    """The authenticated user, as exposed to their own frontend."""

    id: str
    email: str
    display_name: str | None = None
    email_verified: bool
    created_at: datetime


class DetailSchema(BaseModel):
    """Generic human-readable outcome message."""

    detail: str
