"""Postgres-backed reads/writes for record embeddings (pgvector).

Used by the embed pipeline (find records without a vector → embed → store) and
shares the catalog session like the other repositories.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from bibliohack.catalog.infrastructure.postgres.models import BibliographicRecordModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class RecordToEmbed:
    """The fields the embedder needs to build a record's embedding text."""

    record_id: UUID
    title: str
    subtitle: str | None
    authors: tuple[str, ...]
    subjects: tuple[str, ...]
    publisher: str | None


class PostgresEmbeddingRepository:
    """Find records lacking an embedding and write vectors back."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def records_needing_embedding(self, *, limit: int) -> list[RecordToEmbed]:
        stmt = (
            select(BibliographicRecordModel)
            .where(BibliographicRecordModel.embedding.is_(None))
            .options(
                selectinload(BibliographicRecordModel.contributors),
                selectinload(BibliographicRecordModel.subjects),
            )
            .order_by(BibliographicRecordModel.titn.desc())  # newest first
            .limit(limit)
        )
        records = (await self._session.execute(stmt)).scalars().all()
        return [
            RecordToEmbed(
                record_id=r.id,
                title=r.title,
                subtitle=r.subtitle,
                authors=tuple(c.name for c in r.contributors if c.role == "author"),
                subjects=tuple(s.subject for s in r.subjects),
                publisher=r.publisher,
            )
            for r in records
        ]

    async def store_embedding(self, record_id: UUID, vector: list[float]) -> None:
        await self._session.execute(
            update(BibliographicRecordModel)
            .where(BibliographicRecordModel.id == record_id)
            .values(embedding=vector)
        )

    async def count_missing(self) -> int:
        stmt = select(func.count()).where(BibliographicRecordModel.embedding.is_(None))
        return int((await self._session.execute(stmt)).scalar_one())
