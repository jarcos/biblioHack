"""Postgres-backed `CoverRepository`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bibliohack.catalog.infrastructure.postgres.models import IsbnModel
from bibliohack.covers.domain.cover import Cover, CoverSource, CoverStatus
from bibliohack.covers.infrastructure.postgres.models import CoverModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PostgresCoverRepository:
    """Concrete `CoverRepository` backed by the `covers` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_isbn(self, isbn: str) -> Cover | None:
        row = (
            await self._session.execute(select(CoverModel).where(CoverModel.isbn_13 == isbn))
        ).scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def upsert(self, cover: Cover) -> None:
        values = {
            "isbn_13": cover.isbn_13,
            "status": cover.status.value,
            "source": cover.source.value,
            "record_id": cover.record_id,
            "license": cover.license,
            "sha256": cover.sha256,
            "width": cover.width,
            "height": cover.height,
            "fetched_at": cover.fetched_at,
        }
        stmt = pg_insert(CoverModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["isbn_13"],
            set_={key: value for key, value in values.items() if key != "isbn_13"},
        )
        await self._session.execute(stmt)

    async def isbns_needing_cover(self, *, limit: int) -> list[str]:
        """Catalog ISBN-13s with no `covers` row yet.

        A read-model join into the catalog `isbns` table — the same pragmatic
        cross-context read shape the catalog read repo uses for holdings.
        """
        already_known = select(CoverModel.isbn_13)
        stmt = (
            select(IsbnModel.isbn)
            .where(IsbnModel.isbn.not_in(already_known))
            .distinct()
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars())


def _to_domain(row: CoverModel) -> Cover:
    return Cover(
        isbn_13=row.isbn_13,
        status=CoverStatus(row.status),
        source=CoverSource(row.source),
        record_id=row.record_id,
        license=row.license,
        sha256=row.sha256,
        width=row.width,
        height=row.height,
        fetched_at=row.fetched_at,
    )
