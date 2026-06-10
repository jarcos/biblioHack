"""Logging `Mailer` — the no-SMTP fallback (local dev, tests).

When `smtp_host` is unset we log the mail instead of failing the request:
registration still works in dev, and the verification link is right there in
the structured log output.
"""

from __future__ import annotations

import structlog


class LogMailer:
    """Concrete `Mailer` that writes the mail to the structured log."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        structlog.get_logger().warning(
            "mailer.smtp_not_configured_logging_instead",
            to=to,
            subject=subject,
            body=body,
        )
