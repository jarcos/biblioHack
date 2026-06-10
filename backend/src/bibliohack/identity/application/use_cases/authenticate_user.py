"""AuthenticateUser — verify credentials and open a server-side session.

Anti-enumeration: unknown email and wrong password return the same
`INVALID_CREDENTIALS`, and the unknown-email path still performs one hash
computation so its timing matches the wrong-password path. Opportunistic
rehash: when parameters have been strengthened since the hash was created,
a successful login transparently re-hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bibliohack.identity.application.errors import LoginError
from bibliohack.shared.application.result import Err, Ok

if TYPE_CHECKING:
    from bibliohack.identity.application.ports import (
        PasswordHasher,
        SessionStore,
        UserRepository,
    )
    from bibliohack.identity.domain.user import User
    from bibliohack.shared.application.result import Result


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """A fresh session id plus the user it belongs to (for the response body)."""

    session_id: str
    user: User


class AuthenticateUser:
    def __init__(
        self,
        *,
        users: UserRepository,
        hasher: PasswordHasher,
        sessions: SessionStore,
        require_verified_email: bool = True,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._sessions = sessions
        self._require_verified_email = require_verified_email

    async def execute(
        self, *, email: str, password: str
    ) -> Result[AuthenticatedSession, LoginError]:
        user = await self._users.get_by_email(email.strip().lower())
        if user is None:
            # Burn comparable CPU to the verify() below so response timing
            # doesn't reveal whether the email exists.
            self._hasher.hash(password)
            return Err(LoginError.INVALID_CREDENTIALS)

        if not self._hasher.verify(password, user.password_hash.value):
            return Err(LoginError.INVALID_CREDENTIALS)

        if self._require_verified_email and not user.email_verified:
            return Err(LoginError.EMAIL_NOT_VERIFIED)

        if self._hasher.needs_rehash(user.password_hash.value):
            await self._users.update_password_hash(str(user.id), self._hasher.hash(password))

        session_id = await self._sessions.create(str(user.id))
        return Ok(AuthenticatedSession(session_id=session_id, user=user))
