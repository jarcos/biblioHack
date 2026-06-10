"""ResetPassword — redeem a reset token, set the new hash, revoke sessions.

Revoking every live session after a reset matters: the reset's whole premise
is that the old credential may be compromised, so anything authenticated
with it must die too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.identity.application.errors import ResetPasswordError, is_acceptable_password
from bibliohack.identity.application.ports import TokenPurpose
from bibliohack.shared.application.result import Err, Ok

if TYPE_CHECKING:
    from bibliohack.identity.application.ports import (
        PasswordHasher,
        SessionStore,
        TokenService,
        UserRepository,
    )
    from bibliohack.shared.application.result import Result


class ResetPassword:
    def __init__(
        self,
        *,
        users: UserRepository,
        hasher: PasswordHasher,
        tokens: TokenService,
        sessions: SessionStore,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._tokens = tokens
        self._sessions = sessions

    async def execute(self, *, token: str, new_password: str) -> Result[None, ResetPasswordError]:
        # Password check first: a weak password must not burn the token.
        if not is_acceptable_password(new_password):
            return Err(ResetPasswordError.WEAK_PASSWORD)

        user_id = await self._tokens.consume(token, TokenPurpose.PASSWORD_RESET)
        if user_id is None:
            return Err(ResetPasswordError.INVALID_OR_EXPIRED)

        await self._users.update_password_hash(user_id, self._hasher.hash(new_password))
        await self._sessions.delete_for_user(user_id)
        return Ok(None)
