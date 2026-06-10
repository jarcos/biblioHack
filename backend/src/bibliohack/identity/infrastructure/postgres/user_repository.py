"""Postgres-backed `UserRepository`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select, update

from bibliohack.identity.domain.user import Email, PasswordHash, User, UserId
from bibliohack.identity.infrastructure.postgres.models import UserModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _to_domain(model: UserModel) -> User:
    return User(
        user_id=UserId(value=model.id),
        email=Email(model.email),
        password_hash=PasswordHash(model.password_hash),
        email_verified=model.email_verified,
        display_name=model.display_name,
        created_at=model.created_at,
    )


class PostgresUserRepository:
    """Concrete `UserRepository` backed by SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        model = (
            await self._session.execute(select(UserModel).where(UserModel.email == email).limit(1))
        ).scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def get_by_id(self, user_id: str) -> User | None:
        model = await self._session.get(UserModel, UUID(user_id))
        return _to_domain(model) if model is not None else None

    async def add(self, user: User) -> None:
        self._session.add(
            UserModel(
                id=user.id.value,
                email=user.email.value,
                password_hash=user.password_hash.value,
                email_verified=user.email_verified,
                display_name=user.display_name,
            )
        )
        await self._session.flush()

    async def set_email_verified(self, user_id: str) -> None:
        await self._session.execute(
            update(UserModel)
            .where(UserModel.id == UUID(user_id))
            .values(email_verified=True, updated_at=datetime.now(UTC))
        )

    async def update_password_hash(self, user_id: str, password_hash: str) -> None:
        await self._session.execute(
            update(UserModel)
            .where(UserModel.id == UUID(user_id))
            .values(password_hash=password_hash, updated_at=datetime.now(UTC))
        )

    async def delete(self, user_id: str) -> None:
        await self._session.execute(delete(UserModel).where(UserModel.id == UUID(user_id)))
