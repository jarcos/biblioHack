"""RequestPasswordReset — mail a reset link if the account exists.

Deliberately returns nothing either way: revealing whether an email has an
account would let anyone enumerate users from the reset form.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.identity.application.ports import TokenPurpose

if TYPE_CHECKING:
    from bibliohack.identity.application.ports import Mailer, TokenService, UserRepository

_SUBJECT = "biblioHack — restablecer contraseña"
_BODY_TEMPLATE = (
    "Hola,\n"
    "\n"
    "Se ha pedido restablecer la contraseña de tu cuenta de biblioHack.\n"
    "Si has sido tú, usa este enlace (caduca en 2 horas):\n"
    "\n"
    "{link}\n"
    "\n"
    "Si no lo has pedido, ignora este mensaje — tu contraseña no cambia.\n"
)


class RequestPasswordReset:
    def __init__(
        self,
        *,
        users: UserRepository,
        tokens: TokenService,
        mailer: Mailer,
        public_base_url: str,
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._mailer = mailer
        self._public_base_url = public_base_url.rstrip("/")

    async def execute(self, *, email: str) -> None:
        user = await self._users.get_by_email(email.strip().lower())
        if user is None:
            return  # silently — no enumeration
        token = await self._tokens.issue(str(user.id), TokenPurpose.PASSWORD_RESET)
        await self._mailer.send(
            to=user.email.value,
            subject=_SUBJECT,
            body=_BODY_TEMPLATE.format(
                link=f"{self._public_base_url}/reset-password?token={token}"
            ),
        )
