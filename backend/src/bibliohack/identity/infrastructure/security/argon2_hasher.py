"""Argon2id `PasswordHasher` (argon2-cffi) — the AuthProvider of §4.

The encoded string self-describes its parameters, so tuning the settings
later doesn't invalidate old hashes: `needs_rehash` flags them and login
transparently re-hashes.
"""

from __future__ import annotations

from argon2 import PasswordHasher as _Argon2Hasher
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2PasswordHasher:
    """Concrete `PasswordHasher` over argon2-cffi (Argon2id variant)."""

    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost_kib: int = 65536,
        parallelism: int = 4,
    ) -> None:
        self._hasher = _Argon2Hasher(
            time_cost=time_cost,
            memory_cost=memory_cost_kib,
            parallelism=parallelism,
        )

    def hash(self, plain: str) -> str:
        return self._hasher.hash(plain)

    def verify(self, plain: str, hashed: str) -> bool:
        try:
            return self._hasher.verify(hashed, plain)
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, hashed: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(hashed)
        except InvalidHashError:
            return True
