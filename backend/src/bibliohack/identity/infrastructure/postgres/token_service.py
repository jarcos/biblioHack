"""Postgres-backed `TokenService` — hashed, expiring, single-use tokens.

The raw token (256 bits, URL-safe) travels only in the email; the database
stores its SHA-256 hex digest. Consumption is a single conditional UPDATE
(`consumed_at IS NULL AND expires_at > now()`), so a token can't be redeemed
twice even by concurrent requests.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import update

from bibliohack.identity.application.ports import TokenPurpose
from bibliohack.identity.infrastructure.postgres.models import (
    EmailVerificationTokenModel,
    PasswordResetTokenModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_MODEL_FOR_PURPOSE: dict[
    TokenPurpose, type[EmailVerificationTokenModel] | type[PasswordResetTokenModel]
] = {
    TokenPurpose.EMAIL_VERIFICATION: EmailVerificationTokenModel,
    TokenPurpose.PASSWORD_RESET: PasswordResetTokenModel,
}

_TTL_FOR_PURPOSE = {
    TokenPurpose.EMAIL_VERIFICATION: timedelta(hours=24),
    TokenPurpose.PASSWORD_RESET: timedelta(hours=2),
}


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class PostgresTokenService:
    """Concrete `TokenService` over the two token tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue(self, user_id: str, purpose: TokenPurpose) -> str:
        raw = secrets.token_urlsafe(32)
        model_cls = _MODEL_FOR_PURPOSE[purpose]
        self._session.add(
            model_cls(
                id=uuid4(),
                user_id=UUID(user_id),
                token_hash=_digest(raw),
                expires_at=datetime.now(UTC) + _TTL_FOR_PURPOSE[purpose],
            )
        )
        await self._session.flush()
        return raw

    async def consume(self, token: str, purpose: TokenPurpose) -> str | None:
        model_cls = _MODEL_FOR_PURPOSE[purpose]
        now = datetime.now(UTC)
        user_id = (
            await self._session.execute(
                update(model_cls)
                .where(
                    model_cls.token_hash == _digest(token),
                    model_cls.consumed_at.is_(None),
                    model_cls.expires_at > now,
                )
                .values(consumed_at=now)
                .returning(model_cls.user_id)
            )
        ).scalar_one_or_none()
        return str(user_id) if user_id is not None else None
