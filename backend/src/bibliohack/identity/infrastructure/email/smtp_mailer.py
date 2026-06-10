"""SMTP `Mailer` pointed at the NAS mail service (decided 2026-06-09).

Plain stdlib smtplib pushed onto a worker thread — transactional volume here
is tiny (verification + reset mails), so a connection per message is fine and
keeps us dependency-free. STARTTLS by default; login only when credentials
are configured (a LAN relay may not need them).
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage


class SmtpMailer:
    """Concrete `Mailer` over smtplib (sync send on a thread)."""

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        use_starttls: bool = True,
        from_address: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_starttls = use_starttls
        self._from = from_address
        self._timeout = timeout_seconds

    async def send(self, *, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
            if self._use_starttls:
                smtp.starttls()
            if self._username:
                smtp.login(self._username, self._password)
            smtp.send_message(message)
