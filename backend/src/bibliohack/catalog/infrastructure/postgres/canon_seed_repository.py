"""Postgres-backed :class:`CanonSeedRepository` — upsert + the C1 match path.

Two responsibilities, both set-based where it matters:

* **Upsert (C0).** A batch insert with
  ``ON CONFLICT (source, source_ref) DO UPDATE`` of the mutable fields only —
  ``matched_record_id`` / ``acquire_status`` are owned by the matcher and the
  acquisition path, so a refresh never clobbers them. Insert-vs-update is read
  back per row via the ``xmax = 0`` trick (same as the shelf importer).
* **Matching (C1).** ISBN-13 overlap against the ``isbns`` table (authoritative)
  then a conservative ``pg_trgm`` title(+author) fallback, reusing the exact
  thresholds the Goodreads matcher settled on so canon matching inherits its
  precision-over-recall stance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import Result, case, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bibliohack.catalog.application.ports import (
    CanonCoverage,
    CanonSeedRow,
    CanonUpsertResult,
)
from bibliohack.catalog.domain.canon import AcquireStatus, CanonMatchVia
from bibliohack.catalog.infrastructure.postgres.models import (
    BibliographicRecordModel,
    CanonSeedModel,
    ContributorModel,
    IsbnModel,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from bibliohack.catalog.domain.canon import CanonSeedWork

# Trigram thresholds — identical to the Goodreads matcher (see
# reading_history shelf_repository). Precision over recall: a wrong link
# pollutes the canon signal, a miss simply re-matches as the catalogue grows.
_TITLE_SIMILARITY_MIN = 0.5
_AUTHOR_SIMILARITY_MIN = 0.3


class PostgresCanonSeedRepository:
    """Concrete ``CanonSeedRepository`` backed by SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_works(self, works: Sequence[CanonSeedWork]) -> CanonUpsertResult:
        if not works:
            return CanonUpsertResult()

        # Dedup within the batch by identity — ON CONFLICT DO UPDATE can't touch
        # the same row twice in one statement. Last occurrence wins.
        by_identity: dict[tuple[str, str], CanonSeedWork] = {}
        for work in works:
            by_identity[(str(work.source), work.source_ref)] = work

        values = [
            {
                "id": uuid4(),
                "source": str(work.source),
                "source_ref": work.source_ref,
                "title": work.title,
                "author": work.author,
                "pub_year": work.pub_year,
                "isbn13": list(work.isbn13),
                "awards": list(work.awards),
                "notability": work.notability,
            }
            for work in by_identity.values()
        ]

        insert_stmt = pg_insert(CanonSeedModel).values(values)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["source", "source_ref"],
            set_={
                "title": insert_stmt.excluded.title,
                "author": insert_stmt.excluded.author,
                "pub_year": insert_stmt.excluded.pub_year,
                "isbn13": insert_stmt.excluded.isbn13,
                "awards": insert_stmt.excluded.awards,
                "notability": insert_stmt.excluded.notability,
                "updated_at": func.now(),
            },
        )
        # `xmax = 0` is true only for a freshly inserted tuple; on the UPDATE
        # branch of ON CONFLICT the conflicting tuple's xmax is non-zero.
        result: Result[Any] = await self._session.execute(
            upsert_stmt.returning(literal_column("(xmax = 0)"))
        )
        inserted = sum(1 for was_insert in result.scalars() if was_insert)
        return CanonUpsertResult(inserted=inserted, updated=len(values) - inserted)

    async def iter_unmatched(self, *, limit: int, offset: int = 0) -> Sequence[CanonSeedRow]:
        stmt = (
            select(
                CanonSeedModel.id,
                CanonSeedModel.title,
                CanonSeedModel.author,
                CanonSeedModel.isbn13,
            )
            .where(CanonSeedModel.matched_record_id.is_(None))
            # Most notable first, so a bounded run links the marquee names first.
            .order_by(CanonSeedModel.notability.desc(), CanonSeedModel.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            CanonSeedRow(
                id=str(row.id),
                title=row.title,
                author=row.author,
                isbn13=tuple(row.isbn13 or ()),
            )
            for row in result
        ]

    async def match_isbn13(self, isbns: Sequence[str]) -> str | None:
        if not isbns:
            return None
        record_id = (
            await self._session.execute(
                select(IsbnModel.record_id).where(IsbnModel.isbn.in_(list(isbns))).limit(1)
            )
        ).scalar_one_or_none()
        return str(record_id) if record_id is not None else None

    async def match_title_author(self, title: str, author: str | None) -> str | None:
        title_sim = func.similarity(BibliographicRecordModel.title, title)
        stmt = (
            select(BibliographicRecordModel.id)
            .where(title_sim >= _TITLE_SIMILARITY_MIN)
            .order_by(title_sim.desc())
            .limit(1)
        )
        if author:
            author_match = (
                select(ContributorModel.record_id)
                .where(
                    ContributorModel.record_id == BibliographicRecordModel.id,
                    ContributorModel.role == "author",
                    func.similarity(ContributorModel.name, author) >= _AUTHOR_SIMILARITY_MIN,
                )
                .exists()
            )
            stmt = stmt.where(author_match)

        record_id = (await self._session.execute(stmt)).scalar_one_or_none()
        return str(record_id) if record_id is not None else None

    async def link_match(self, seed_id: str, record_id: str, via: CanonMatchVia) -> None:
        # A row we'd resolved + seeded (acquire_status='held') has now landed in
        # the mirror, so advance it to 'ingested'; leave any other status as-is.
        held = str(AcquireStatus.HELD)
        ingested = str(AcquireStatus.INGESTED)
        await self._session.execute(
            update(CanonSeedModel)
            .where(CanonSeedModel.id == UUID(seed_id))
            .values(
                matched_record_id=UUID(record_id),
                matched_via=str(via),
                acquire_status=case(
                    (CanonSeedModel.acquire_status == held, ingested),
                    else_=CanonSeedModel.acquire_status,
                ),
                updated_at=func.now(),
            )
        )

    async def coverage(self) -> CanonCoverage:
        isbn_via = str(CanonMatchVia.ISBN)
        ta_via = str(CanonMatchVia.TITLE_AUTHOR)
        stmt = select(
            func.count().label("total"),
            func.count().filter(CanonSeedModel.matched_via == isbn_via).label("isbn"),
            func.count().filter(CanonSeedModel.matched_via == ta_via).label("title_author"),
            func.count().filter(CanonSeedModel.matched_record_id.is_(None)).label("unmatched"),
        )
        row = (await self._session.execute(stmt)).one()
        return CanonCoverage(
            total=row.total,
            matched_isbn=row.isbn,
            matched_title_author=row.title_author,
            unmatched=row.unmatched,
        )

    async def iter_resolvable(self, *, limit: int) -> Sequence[CanonSeedRow]:
        unchecked = str(AcquireStatus.UNCHECKED)
        stmt = (
            select(
                CanonSeedModel.id,
                CanonSeedModel.title,
                CanonSeedModel.author,
                CanonSeedModel.isbn13,
            )
            .where(
                CanonSeedModel.matched_record_id.is_(None),
                CanonSeedModel.acquire_status == unchecked,
                # at least one ISBN — the precise resolve key
                func.cardinality(CanonSeedModel.isbn13) > 0,
            )
            .order_by(CanonSeedModel.notability.desc(), CanonSeedModel.id)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            CanonSeedRow(
                id=str(row.id),
                title=row.title,
                author=row.author,
                isbn13=tuple(row.isbn13 or ()),
            )
            for row in result
        ]

    async def set_acquire_status(self, seed_id: str, status: AcquireStatus) -> None:
        await self._session.execute(
            update(CanonSeedModel)
            .where(CanonSeedModel.id == UUID(seed_id))
            .values(acquire_status=str(status), updated_at=func.now())
        )
