"""Postgres-backed reads/writes for record embeddings (pgvector).

Used by the embed pipeline (find records without a vector → embed → store) and
shares the catalog session like the other repositories.

The backfill queue follows the precomputed relevance score, highest first. The
mirror holds ~1.7M records and the embed job gets through a few hundred per
run, so the order decides which books get semantic search, "más como este" and
recommendations soonest. TITN order (the old one) put every new acquisition
ahead of the whole backlist; relevance puts the books readers are likely to
meet first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from bibliohack.catalog.infrastructure.postgres.models import (
    BibliographicRecordModel,
    RecordRelevanceModel,
)

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


@dataclass(frozen=True, slots=True)
class EmbeddedSample:
    """A record that already has a vector, with that vector (parity checks)."""

    record: RecordToEmbed
    vector: list[float]


class PostgresEmbeddingRepository:
    """Find records lacking an embedding and write vectors back."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def records_needing_embedding(self, *, limit: int) -> list[RecordToEmbed]:
        stmt = (
            select(BibliographicRecordModel)
            # INNER JOIN, as /browse does: every record has a relevance row
            # (the AFTER INSERT trigger seeds it), and the inner join lets the
            # planner walk ix_record_relevance_score instead of sorting ~1.5M
            # rows each run.
            .join(
                RecordRelevanceModel,
                RecordRelevanceModel.record_id == BibliographicRecordModel.id,
            )
            .where(BibliographicRecordModel.embedding.is_(None))
            .options(
                selectinload(BibliographicRecordModel.contributors),
                selectinload(BibliographicRecordModel.subjects),
            )
            .order_by(
                RecordRelevanceModel.score.desc(),
                BibliographicRecordModel.titn.desc(),  # ties: newest first
            )
            .limit(limit)
        )
        records = (await self._session.execute(stmt)).scalars().all()
        return [_to_embed(r) for r in records]

    async def sample_embedded(self, *, limit: int) -> list[EmbeddedSample]:
        """A random handful of already-embedded records, with their vectors."""
        stmt = (
            select(BibliographicRecordModel)
            .where(BibliographicRecordModel.embedding.is_not(None))
            .options(
                selectinload(BibliographicRecordModel.contributors),
                selectinload(BibliographicRecordModel.subjects),
            )
            .order_by(func.random())
            .limit(limit)
        )
        records = (await self._session.execute(stmt)).scalars().all()
        return [EmbeddedSample(record=_to_embed(r), vector=_stored_vector(r)) for r in records]

    async def store_embedding(self, record_id: UUID, vector: list[float]) -> None:
        await self._session.execute(
            update(BibliographicRecordModel)
            .where(BibliographicRecordModel.id == record_id)
            .values(embedding=vector)
        )

    async def count_missing(self) -> int:
        stmt = select(func.count()).where(BibliographicRecordModel.embedding.is_(None))
        return int((await self._session.execute(stmt)).scalar_one())


def _to_embed(r: BibliographicRecordModel) -> RecordToEmbed:
    return RecordToEmbed(
        record_id=r.id,
        title=r.title,
        subtitle=r.subtitle,
        authors=tuple(c.name for c in r.contributors if c.role == "author"),
        subjects=tuple(s.subject for s in r.subjects),
        publisher=r.publisher,
    )


def _stored_vector(r: BibliographicRecordModel) -> list[float]:
    # Only called on rows selected with `embedding IS NOT NULL`. pgvector hands
    # back a numpy array, hence the explicit None check instead of `or`.
    assert r.embedding is not None
    return [float(x) for x in r.embedding]
