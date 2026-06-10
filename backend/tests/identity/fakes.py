"""In-memory fakes for the identity ports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bibliohack.identity.application.ports import TokenPurpose
    from bibliohack.identity.domain.user import User


class InMemoryUserRepository:
    def __init__(self) -> None:
        self.users: dict[str, User] = {}

    async def get_by_email(self, email: str) -> User | None:
        lowered = email.lower()
        return next((u for u in self.users.values() if u.email.value == lowered), None)

    async def get_by_id(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    async def add(self, user: User) -> None:
        self.users[str(user.id)] = user

    async def set_email_verified(self, user_id: str) -> None:
        self.users[user_id].mark_email_verified()

    async def update_password_hash(self, user_id: str, password_hash: str) -> None:
        from bibliohack.identity.domain.user import PasswordHash

        self.users[user_id].change_password(PasswordHash(password_hash))


class FakePasswordHasher:
    """Reversible 'hash' for tests — NOT a real hasher."""

    def __init__(self, *, needs_rehash: bool = False) -> None:
        self._needs_rehash = needs_rehash
        self.hash_calls = 0

    def hash(self, plain: str) -> str:
        self.hash_calls += 1
        return f"fakehash:{plain}"

    def verify(self, plain: str, hashed: str) -> bool:
        return hashed == f"fakehash:{plain}"

    def needs_rehash(self, hashed: str) -> bool:
        return self._needs_rehash


class InMemorySessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, str] = {}
        self._counter = 0

    async def create(self, user_id: str) -> str:
        self._counter += 1
        session_id = f"sess-{self._counter}"
        self.sessions[session_id] = user_id
        return session_id

    async def get(self, session_id: str) -> str | None:
        return self.sessions.get(session_id)

    async def delete(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    async def delete_for_user(self, user_id: str) -> None:
        self.sessions = {sid: uid for sid, uid in self.sessions.items() if uid != user_id}


class InMemoryTokenService:
    def __init__(self) -> None:
        self.tokens: dict[str, tuple[str, TokenPurpose]] = {}
        self._counter = 0

    async def issue(self, user_id: str, purpose: TokenPurpose) -> str:
        self._counter += 1
        token = f"tok-{purpose.value}-{self._counter}"
        self.tokens[token] = (user_id, purpose)
        return token

    async def consume(self, token: str, purpose: TokenPurpose) -> str | None:
        entry = self.tokens.get(token)
        if entry is None or entry[1] is not purpose:
            return None
        del self.tokens[token]
        return entry[0]


class RecordingMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []  # (to, subject, body)

    async def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


class AlwaysPassCaptcha:
    async def verify(self, token: str | None, remote_ip: str | None = None) -> bool:
        return True


class AlwaysFailCaptcha:
    async def verify(self, token: str | None, remote_ip: str | None = None) -> bool:
        return False
