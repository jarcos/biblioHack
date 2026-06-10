"""FastAPI router for account self-service (/api/account) — GDPR endpoints.

- GET    /api/account/export — the caller's full data, as a JSON download.
- DELETE /api/account        — erase the account; requires the password
  again (a stolen cookie alone must not be able to destroy data).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Runtime imports — FastAPI evaluates endpoint signatures at runtime (see
# the note in identity/interfaces/http/dependencies.py).
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from bibliohack.identity.application.ports import (  # noqa: TC001
    PasswordHasher,
    SessionStore,
    UserRepository,
)
from bibliohack.identity.application.use_cases.delete_account import DeleteAccount
from bibliohack.identity.domain.user import User  # noqa: TC001
from bibliohack.identity.infrastructure.postgres.account_export import PostgresAccountExporter
from bibliohack.identity.interfaces.http.dependencies import (
    get_current_user,
    get_password_hasher,
    get_session_store,
    get_user_repository,
)
from bibliohack.interfaces.http.dependencies import get_tx_session
from bibliohack.shared.application.result import Err
from bibliohack.shared.infrastructure.settings import Settings, get_settings

router = APIRouter(prefix="/api/account", tags=["account"])


class DeleteAccountRequestSchema(BaseModel):
    password: str = Field(..., max_length=1024)


@router.get("/export")
async def export_account(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> JSONResponse:
    """Everything we hold about the caller, as a downloadable JSON file."""
    payload = await PostgresAccountExporter(session).export(str(user.id))
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": 'attachment; filename="bibliohack-export.json"'},
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    payload: DeleteAccountRequestSchema,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
    hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
) -> None:
    """Erase the account: user row + cascades + every session, then the cookie."""
    result = await DeleteAccount(users=users, hasher=hasher, sessions=sessions).execute(
        user_id=str(user.id), password=payload.password
    )
    if isinstance(result, Err):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=result.error.value,
        )
    response.delete_cookie(
        key=settings.session_cookie_name,
        domain=settings.session_cookie_domain,
        path="/",
    )
