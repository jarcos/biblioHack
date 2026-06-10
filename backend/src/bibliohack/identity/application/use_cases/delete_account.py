"""DeleteAccount — re-authenticate, then erase the user (GDPR Art. 17).

The password check matters: a stolen session cookie alone must not be able
to destroy the account. The user row's FK cascades take the shelf, import
jobs and recommendations with it; every live session is revoked so the
cookie dies too.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from bibliohack.shared.application.result import Err, Ok

if TYPE_CHECKING:
    from bibliohack.identity.application.ports import (
        PasswordHasher,
        SessionStore,
        UserRepository,
    )
    from bibliohack.shared.application.result import Result


class DeleteAccountError(StrEnum):
    INVALID_PASSWORD = "invalid_password"  # noqa: S105 — error code, not a credential


class DeleteAccount:
    def __init__(
        self,
        *,
        users: UserRepository,
        hasher: PasswordHasher,
        sessions: SessionStore,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._sessions = sessions

    async def execute(self, *, user_id: str, password: str) -> Result[None, DeleteAccountError]:
        user = await self._users.get_by_id(user_id)
        if user is None:
            return Err(DeleteAccountError.INVALID_PASSWORD)  # already gone — same answer
        if not self._hasher.verify(password, user.password_hash.value):
            return Err(DeleteAccountError.INVALID_PASSWORD)

        await self._users.delete(user_id)
        await self._sessions.delete_for_user(user_id)
        return Ok(None)
