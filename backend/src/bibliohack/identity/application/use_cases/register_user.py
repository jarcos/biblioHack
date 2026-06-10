"""RegisterUser — create an unverified account and mail a verification link.

Public registration: anyone may sign up, so the account starts unverified
and login stays blocked until the emailed token is consumed (VerifyEmail).
The kill-switch (`registration_enabled`) short-circuits everything — it's the
operator's abuse response while better mitigations are deployed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.identity.application.errors import RegisterError, is_acceptable_password
from bibliohack.identity.application.ports import TokenPurpose
from bibliohack.identity.domain.user import Email, PasswordHash, User
from bibliohack.shared.application.result import Err, Ok

if TYPE_CHECKING:
    from bibliohack.identity.application.ports import (
        Mailer,
        PasswordHasher,
        TokenService,
        UserRepository,
    )
    from bibliohack.shared.application.result import Result

_SUBJECT = "biblioHack — confirma tu correo"
_BODY_TEMPLATE = (
    "Hola{name_part},\n"
    "\n"
    "Alguien (esperamos que tú) ha creado una cuenta en biblioHack con este\n"
    "correo. Para activarla, confirma tu dirección:\n"
    "\n"
    "{link}\n"
    "\n"
    "El enlace caduca en 24 horas. Si no has sido tú, ignora este mensaje\n"
    "y la cuenta no se activará.\n"
)


class RegisterUser:
    """Create the user, then mail the verification link."""

    def __init__(
        self,
        *,
        users: UserRepository,
        hasher: PasswordHasher,
        tokens: TokenService,
        mailer: Mailer,
        registration_enabled: bool,
        public_base_url: str,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._tokens = tokens
        self._mailer = mailer
        self._registration_enabled = registration_enabled
        self._public_base_url = public_base_url.rstrip("/")

    async def execute(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> Result[str, RegisterError]:
        """Returns the new user's id, or why registration was refused."""
        if not self._registration_enabled:
            return Err(RegisterError.REGISTRATION_DISABLED)

        try:
            valid_email = Email(email)
        except ValueError:
            return Err(RegisterError.INVALID_EMAIL)

        if not is_acceptable_password(password):
            return Err(RegisterError.WEAK_PASSWORD)

        if await self._users.get_by_email(valid_email.value) is not None:
            return Err(RegisterError.EMAIL_TAKEN)

        user = User.register(
            email=valid_email,
            password_hash=PasswordHash(self._hasher.hash(password)),
            display_name=display_name,
        )
        await self._users.add(user)

        token = await self._tokens.issue(str(user.id), TokenPurpose.EMAIL_VERIFICATION)
        name_part = f" {display_name}" if display_name else ""
        await self._mailer.send(
            to=valid_email.value,
            subject=_SUBJECT,
            body=_BODY_TEMPLATE.format(
                name_part=name_part,
                link=f"{self._public_base_url}/verify?token={token}",
            ),
        )
        return Ok(str(user.id))
