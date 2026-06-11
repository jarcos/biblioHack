"""FastAPI router for authentication (/api/auth/*).

Under /api/* per the tunnel-routing rule — anything else would hit the
static frontend. Sessions ride an httpOnly cookie (set on login, cleared on
logout); the SPA islands call these endpoints with `credentials: "include"`.

The abuse-prone endpoints are rate-limited per client IP (Redis fixed
window, fail-open): registration and reset-request because they send mail,
login because it's the brute-force target. Limits live as module-level
names so tests can override them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from bibliohack.identity.application.errors import LoginError, RegisterError

# Runtime imports (not TYPE_CHECKING): FastAPI evaluates endpoint signatures at
# runtime — see the note in identity/interfaces/http/dependencies.py.
from bibliohack.identity.application.ports import (  # noqa: TC001
    CaptchaVerifier,
    Mailer,
    PasswordHasher,
    SessionStore,
    TokenService,
    UserRepository,
)
from bibliohack.identity.application.use_cases.authenticate_user import AuthenticateUser
from bibliohack.identity.application.use_cases.register_user import RegisterUser
from bibliohack.identity.application.use_cases.request_password_reset import RequestPasswordReset
from bibliohack.identity.application.use_cases.reset_password import ResetPassword
from bibliohack.identity.application.use_cases.verify_email import VerifyEmail
from bibliohack.identity.domain.user import User  # noqa: TC001
from bibliohack.identity.interfaces.http.dependencies import (
    get_captcha_verifier,
    get_current_user,
    get_mailer,
    get_password_hasher,
    get_session_store,
    get_token_service,
    get_user_repository,
)
from bibliohack.identity.interfaces.http.schemas import (
    DetailSchema,
    LoginRequestSchema,
    PasswordResetRequestSchema,
    PasswordResetSchema,
    RegisterRequestSchema,
    UserSchema,
    VerifyEmailRequestSchema,
)
from bibliohack.interfaces.http.dependencies import rate_limit
from bibliohack.shared.application.result import Err
from bibliohack.shared.infrastructure.settings import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Module-level so tests can disable them via dependency_overrides.
register_rate_limit = rate_limit("auth-register", limit=5, window_seconds=3600)
login_rate_limit = rate_limit("auth-login", limit=10, window_seconds=300)
reset_request_rate_limit = rate_limit("auth-reset-request", limit=5, window_seconds=3600)
# Token-consume endpoints: tokens are hashed, single-use and expiring, but an
# unthrottled endpoint is still a brute-force window over the token space.
verify_rate_limit = rate_limit("auth-verify", limit=10, window_seconds=300)
reset_rate_limit = rate_limit("auth-reset", limit=10, window_seconds=300)

_REGISTER_STATUS_FOR_ERROR = {
    RegisterError.REGISTRATION_DISABLED: status.HTTP_403_FORBIDDEN,
    RegisterError.INVALID_EMAIL: status.HTTP_422_UNPROCESSABLE_CONTENT,
    RegisterError.WEAK_PASSWORD: status.HTTP_422_UNPROCESSABLE_CONTENT,
    RegisterError.EMAIL_TAKEN: status.HTTP_409_CONFLICT,
}

_LOGIN_STATUS_FOR_ERROR = {
    LoginError.INVALID_CREDENTIALS: status.HTTP_401_UNAUTHORIZED,
    LoginError.EMAIL_NOT_VERIFIED: status.HTTP_403_FORBIDDEN,
}


def _user_to_schema(user: User) -> UserSchema:
    return UserSchema(
        id=str(user.id),
        email=user.email.value,
        display_name=user.display_name,
        email_verified=user.email_verified,
        created_at=user.created_at,
    )


async def _check_captcha(captcha: CaptchaVerifier, token: str | None, request: Request) -> None:
    client_ip = request.client.host if request.client else None
    if not await captcha.verify(token, client_ip):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="captcha verification failed",
        )


@router.post(
    "/register",
    response_model=DetailSchema,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(register_rate_limit)],
)
async def register(
    payload: RegisterRequestSchema,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
    captcha: Annotated[CaptchaVerifier, Depends(get_captcha_verifier)],
) -> DetailSchema:
    """Create an account (unverified) and send the verification mail."""
    await _check_captcha(captcha, payload.turnstile_token, request)
    result = await RegisterUser(
        users=users,
        hasher=hasher,
        tokens=tokens,
        mailer=mailer,
        registration_enabled=settings.registration_enabled,
        public_base_url=settings.public_base_url,
    ).execute(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
    )
    if isinstance(result, Err):
        raise HTTPException(
            status_code=_REGISTER_STATUS_FOR_ERROR[result.error],
            detail=result.error.value,
        )
    return DetailSchema(detail="account created — check your email to verify it")


@router.post(
    "/verify",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_rate_limit)],
)
async def verify_email(
    payload: VerifyEmailRequestSchema,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> None:
    """Consume an email-verification token."""
    result = await VerifyEmail(users=users, tokens=tokens).execute(payload.token)
    if isinstance(result, Err):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error.value,
        )


@router.post("/login", response_model=UserSchema, dependencies=[Depends(login_rate_limit)])
async def login(
    payload: LoginRequestSchema,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
    captcha: Annotated[CaptchaVerifier, Depends(get_captcha_verifier)],
) -> UserSchema:
    """Verify credentials, open a session, set the httpOnly cookie."""
    await _check_captcha(captcha, payload.turnstile_token, request)
    result = await AuthenticateUser(
        users=users,
        hasher=hasher,
        sessions=sessions,
        require_verified_email=settings.require_verified_email_login,
    ).execute(email=payload.email, password=payload.password)
    if isinstance(result, Err):
        raise HTTPException(
            status_code=_LOGIN_STATUS_FOR_ERROR[result.error],
            detail=result.error.value,
        )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=result.value.session_id,
        max_age=settings.session_ttl_seconds,
        domain=settings.session_cookie_domain,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )
    return _user_to_schema(result.value.user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
) -> None:
    """Kill the server-side session and clear the cookie. Idempotent."""
    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id:
        await sessions.delete(session_id)
    response.delete_cookie(
        key=settings.session_cookie_name,
        domain=settings.session_cookie_domain,
        path="/",
    )


@router.get("/me", response_model=UserSchema)
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> UserSchema:
    """The authenticated user, or 401."""
    return _user_to_schema(user)


@router.post(
    "/password/reset-request",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(reset_request_rate_limit)],
)
async def password_reset_request(
    payload: PasswordResetRequestSchema,
    settings: Annotated[Settings, Depends(get_settings)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> DetailSchema:
    """Always 202 — whether the account exists is never revealed."""
    await RequestPasswordReset(
        users=users,
        tokens=tokens,
        mailer=mailer,
        public_base_url=settings.public_base_url,
    ).execute(email=payload.email)
    return DetailSchema(detail="if that account exists, a reset mail is on its way")


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(reset_rate_limit)],
)
async def password_reset(
    payload: PasswordResetSchema,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
) -> None:
    """Redeem a reset token; revokes every session of the user."""
    result = await ResetPassword(
        users=users,
        hasher=hasher,
        tokens=tokens,
        sessions=sessions,
    ).execute(token=payload.token, new_password=payload.new_password)
    if isinstance(result, Err):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error.value,
        )
