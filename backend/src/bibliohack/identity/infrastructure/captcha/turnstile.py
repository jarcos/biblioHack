"""Cloudflare Turnstile `CaptchaVerifier` (register/login bot protection).

Disabled (always passes) when no secret is configured — local dev and the
period before the Turnstile widget ships in the frontend. With a secret set
it fails CLOSED: missing tokens, network errors and non-2xx responses all
deny, since this guards public registration on a home NAS.
"""

from __future__ import annotations

import httpx
import structlog

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileVerifier:
    """Concrete `CaptchaVerifier` over the Turnstile siteverify API."""

    def __init__(self, *, secret: str, timeout_seconds: float = 10.0) -> None:
        self._secret = secret
        self._timeout = timeout_seconds

    async def verify(self, token: str | None, remote_ip: str | None = None) -> bool:
        if not self._secret:
            return True  # not configured — feature off
        if not token:
            return False

        payload = {"secret": self._secret, "response": token}
        if remote_ip:
            payload["remoteip"] = remote_ip
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(_VERIFY_URL, data=payload)
                response.raise_for_status()
                return bool(response.json().get("success", False))
        except httpx.HTTPError:
            structlog.get_logger().warning("turnstile.verify_failed_denying")
            return False
