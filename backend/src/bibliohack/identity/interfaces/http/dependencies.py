"""FastAPI providers for the identity ports, plus the auth dependencies.

Each port gets a small provider function so tests can swap in fakes via
`app.dependency_overrides` without a database or Redis. `get_current_user` /
`get_optional_user` live here (not in the shared dependencies module) to
avoid a circular import — shared deps must not import identity, which
imports shared deps. Other contexts import them from here when they grow
user-scoped endpoints (Phase 2).
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request, status

# Runtime imports (not TYPE_CHECKING): FastAPI evaluates dependency signatures
# at runtime — TYPE_CHECKING-only names would silently degrade `Depends`
# parameters into required query params (same rationale as the shelf router's
# AsyncSession import).
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from bibliohack.identity.application.ports import (  # noqa: TC001
    CaptchaVerifier,
    Mailer,
    PasswordHasher,
    SessionStore,
    TokenService,
    UserRepository,
)
from bibliohack.identity.domain.user import User  # noqa: TC001
from bibliohack.identity.infrastructure.captcha.turnstile import TurnstileVerifier
from bibliohack.identity.infrastructure.email.log_mailer import LogMailer
from bibliohack.identity.infrastructure.email.smtp_mailer import SmtpMailer
from bibliohack.identity.infrastructure.postgres.token_service import PostgresTokenService
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository
from bibliohack.identity.infrastructure.security.argon2_hasher import Argon2PasswordHasher
from bibliohack.identity.infrastructure.sessions.redis_session_store import RedisSessionStore
from bibliohack.interfaces.http.dependencies import get_tx_session
from bibliohack.shared.infrastructure.settings import Settings, get_settings

if TYPE_CHECKING:
    from redis.asyncio import Redis


@lru_cache(maxsize=1)
def _redis_client_for_url(redis_url: str) -> Redis:
    # Imported lazily so unit tests that override get_session_store never
    # touch redis at all.
    from redis.asyncio import Redis

    return Redis.from_url(redis_url)


def get_user_repository(
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> UserRepository:
    return PostgresUserRepository(session)


def get_token_service(
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> TokenService:
    return PostgresTokenService(session)


@lru_cache(maxsize=1)
def _hasher_for_params(time_cost: int, memory_cost_kib: int, parallelism: int) -> PasswordHasher:
    return Argon2PasswordHasher(
        time_cost=time_cost,
        memory_cost_kib=memory_cost_kib,
        parallelism=parallelism,
    )


def get_password_hasher(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PasswordHasher:
    return _hasher_for_params(
        settings.argon2_time_cost,
        settings.argon2_memory_cost_kib,
        settings.argon2_parallelism,
    )


def get_session_store(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionStore:
    return RedisSessionStore(
        _redis_client_for_url(settings.redis_url),
        ttl_seconds=settings.session_ttl_seconds,
    )


def get_mailer(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Mailer:
    if not settings.smtp_host:
        return LogMailer()
    return SmtpMailer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_starttls=settings.smtp_starttls,
        from_address=settings.mail_from,
    )


def get_captcha_verifier(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CaptchaVerifier:
    return TurnstileVerifier(secret=settings.turnstile_secret)


# ─── the cross-cutting auth dependencies ─────────────────────


async def get_optional_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> User | None:
    """The authenticated user, or None — for endpoints that work logged-out."""
    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        return None
    user_id = await sessions.get(session_id)
    if user_id is None:
        return None
    return await users.get_by_id(user_id)


async def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    """The authenticated user — 401 when the session is missing/expired."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
        )
    return user
