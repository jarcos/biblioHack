"""VerifyEmail — consume a verification token and flip the user's flag."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.identity.application.errors import TokenError
from bibliohack.identity.application.ports import TokenPurpose
from bibliohack.shared.application.result import Err, Ok

if TYPE_CHECKING:
    from bibliohack.identity.application.ports import TokenService, UserRepository
    from bibliohack.shared.application.result import Result


class VerifyEmail:
    def __init__(self, *, users: UserRepository, tokens: TokenService) -> None:
        self._users = users
        self._tokens = tokens

    async def execute(self, token: str) -> Result[None, TokenError]:
        user_id = await self._tokens.consume(token, TokenPurpose.EMAIL_VERIFICATION)
        if user_id is None:
            return Err(TokenError.INVALID_OR_EXPIRED)
        await self._users.set_email_verified(user_id)
        return Ok(None)
