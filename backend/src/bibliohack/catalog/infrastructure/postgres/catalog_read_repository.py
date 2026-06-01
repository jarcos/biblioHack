"""Postgres-backed `CatalogReadRepository` for the public API.

Uses SQLAlchemy 2.0 + the `spanish_unaccent` FTS configuration we seeded
in the migration. Search ranks by `ts_rank_cd` so the most relevant
results come first.

Returns DTOs from `catalog/application/dto.py`, not ORM models — the HTTP
layer maps DTOs to Pydantic schemas without ever importing SQLAlchemy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from bibliohack.catalog.application.dto import (
    CatalogRecordSummary,
    CatalogRecordView,
    CopyView,
    SearchPage,
)
from bibliohack.catalog.domain.literary_profile import (
    SearchScope,
    default_scope_audiences,
    default_scope_forms,
)
from bibliohack.catalog.infrastructure.postgres.models import (
    BibliographicRecordModel,
)
from bibliohack.holdings.infrastructure.postgres.models import BranchModel, CopyModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from bibliohack.catalog.domain.titn import Titn

# Hard upper bound on `limit` so a pathological caller can't request a
# million rows in one go.
_MAX_SEARCH_LIMIT = 100


class PostgresCatalogReadRepository:
    """Concrete `CatalogReadRepository` backed by SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_titn(self, titn: Titn) -> CatalogRecordView | None:
        stmt = (
            select(BibliographicRecordModel)
            .where(BibliographicRecordModel.titn == int(titn))
            .options(
                selectinload(BibliographicRecordModel.contributors),
                selectinload(BibliographicRecordModel.subjects),
                selectinload(BibliographicRecordModel.isbns),
            )
        )
        record = (await self._session.execute(stmt)).scalar_one_or_none()
        if record is None:
            return None

        # Fetch copies + branches in one go.
        copies_stmt = (
            select(CopyModel, BranchModel.name)
            .join(BranchModel, BranchModel.code == CopyModel.branch_code)
            .where(CopyModel.record_id == record.id)
            .order_by(BranchModel.name.asc())
        )
        copies_rows = (await self._session.execute(copies_stmt)).all()

        return CatalogRecordView(
            titn=record.titn,
            title=record.title,
            subtitle=record.subtitle,
            document_type=record.document_type,
            language=record.language,
            pub_year=record.pub_year,
            publisher=record.publisher,
            classification=record.classification,
            audience=record.audience,
            literary_form=record.literary_form,
            authors=tuple(c.name for c in record.contributors if c.role == "author"),
            subjects=tuple(s.subject for s in record.subjects),
            isbns=tuple(i.isbn for i in record.isbns),
            copies=tuple(
                CopyView(branch_code=copy.branch_code, branch_name=branch_name)
                for copy, branch_name in copies_rows
            ),
            source_url=record.source_url,
        )

    async def search(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
        scope: SearchScope = SearchScope.LITERARY,
    ) -> SearchPage:
        cleaned = query.strip()
        if not cleaned:
            return SearchPage(query=query, items=(), total=0, limit=limit, offset=offset)

        capped_limit = max(1, min(limit, _MAX_SEARCH_LIMIT))
        capped_offset = max(0, offset)

        # tsquery via plainto_tsquery — handles user input safely (no
        # operator injection) and uses our spanish_unaccent config.
        tsq = func.plainto_tsquery("spanish_unaccent", cleaned)
        rank = func.ts_rank_cd(BibliographicRecordModel.fts, tsq)

        base_q = select(BibliographicRecordModel).where(BibliographicRecordModel.fts.op("@@")(tsq))

        # Default ("literary") scope: adult literature, all genres. Hide only
        # records we are confident are children's/youth or non-fiction;
        # 'unknown' on either axis stays visible. SearchScope.ALL skips this.
        if scope is SearchScope.LITERARY:
            base_q = base_q.where(
                BibliographicRecordModel.audience.in_(default_scope_audiences()),
                BibliographicRecordModel.literary_form.in_(default_scope_forms()),
            )

        # Count first (separate query — keeps the main fetch indexable).
        total = (
            await self._session.execute(select(func.count()).select_from(base_q.subquery()))
        ).scalar_one()

        page_stmt = (
            base_q.options(selectinload(BibliographicRecordModel.contributors))
            .order_by(rank.desc(), BibliographicRecordModel.titn.asc())
            .limit(capped_limit)
            .offset(capped_offset)
        )
        rows = (await self._session.execute(page_stmt)).scalars().all()

        # Copies count per record (one extra round-trip; acceptable for
        # search pages of up to ~100 rows).
        ids = [r.id for r in rows]
        copies_count_by_id: dict[object, int] = {}
        if ids:
            counts_stmt = (
                select(CopyModel.record_id, func.count(CopyModel.id))
                .where(CopyModel.record_id.in_(ids))
                .group_by(CopyModel.record_id)
            )
            copies_count_by_id = {
                rid: int(n) for rid, n in (await self._session.execute(counts_stmt)).all()
            }

        items = tuple(
            CatalogRecordSummary(
                titn=r.titn,
                title=r.title,
                authors=tuple(c.name for c in r.contributors if c.role == "author"),
                publisher=r.publisher,
                pub_year=r.pub_year,
                copies_count=copies_count_by_id.get(r.id, 0),
                audience=r.audience,
                literary_form=r.literary_form,
            )
            for r in rows
        )

        return SearchPage(
            query=query,
            items=items,
            total=int(total),
            limit=capped_limit,
            offset=capped_offset,
        )
