"""Postgres-backed `CatalogReadRepository` for the public API.

Uses SQLAlchemy 2.0 + the `spanish_unaccent` FTS configuration we seeded
in the migration. Search ranks by `ts_rank_cd` so the most relevant
results come first.

Returns DTOs from `catalog/application/dto.py`, not ORM models — the HTTP
layer maps DTOs to Pydantic schemas without ever importing SQLAlchemy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from bibliohack.availability.domain.status import AvailabilityStatus
from bibliohack.availability.infrastructure.postgres.models import AvailabilitySnapshotModel
from bibliohack.catalog.application.dto import (
    AuthorCount,
    BrowsePage,
    CatalogRecordSummary,
    CatalogRecordView,
    CopyView,
    CoverView,
    FacetCount,
    SearchPage,
)
from bibliohack.catalog.domain.literary_profile import (
    SearchScope,
    default_scope_audiences,
    default_scope_forms,
)
from bibliohack.catalog.infrastructure.postgres.models import (
    BibliographicRecordModel,
    ContributorModel,
    IsbnModel,
)
from bibliohack.covers.infrastructure.postgres.models import CoverModel
from bibliohack.holdings.infrastructure.postgres.models import BranchModel, CopyModel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

    from bibliohack.catalog.domain.titn import Titn

# Hard upper bound on `limit` so a pathological caller can't request a
# million rows in one go.
_MAX_SEARCH_LIMIT = 100

# Served, content-addressed cover URL (under /catalog so it rides the existing
# tunnel route to the api). Immutable, so it's safe to cache hard at the edge.
_COVER_URL = "/catalog/covers/{}.webp"
# CoverModel.status value that means the image is in the store (kept as a
# literal here to avoid importing the covers domain enum into this read model).
_COVER_RESOLVED = "resolved"

_SelectT = TypeVar("_SelectT", bound=Select)  # type: ignore[type-arg]


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

        # Enrich each copy with its latest availability snapshot.
        status_by_copy = await self._latest_status_by_copy([copy.id for copy, _ in copies_rows])
        unknown = (AvailabilityStatus.UNKNOWN.value, None)
        copy_views: list[CopyView] = []
        for copy, branch_name in copies_rows:
            status, due_back_at = status_by_copy.get(copy.id, unknown)
            copy_views.append(
                CopyView(
                    branch_code=copy.branch_code,
                    branch_name=branch_name,
                    signature=copy.signature,
                    status=status,
                    due_back_at=due_back_at,
                )
            )

        covers = await self._covers_by_record([record.id])

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
            genre=record.genre,
            authors=tuple(c.name for c in record.contributors if c.role == "author"),
            subjects=tuple(s.subject for s in record.subjects),
            isbns=tuple(i.isbn for i in record.isbns),
            copies=tuple(copy_views),
            source_url=record.source_url,
            cover=covers.get(record.id),
        )

    async def _latest_status_by_copy(
        self, copy_ids: list[object]
    ) -> dict[object, tuple[str, str | None]]:
        """Latest (status, due_back_at) per copy via DISTINCT ON (copy_id).

        Reads the availability context's snapshot table directly — a read-model
        join, the same pragmatic shape as the holdings join above. Returns ISO
        date strings so the application/HTTP layers stay free of `date`.
        """
        if not copy_ids:
            return {}
        stmt = (
            select(
                AvailabilitySnapshotModel.copy_id,
                AvailabilitySnapshotModel.status,
                AvailabilitySnapshotModel.due_back_at,
            )
            .where(AvailabilitySnapshotModel.copy_id.in_(copy_ids))
            .distinct(AvailabilitySnapshotModel.copy_id)
            .order_by(
                AvailabilitySnapshotModel.copy_id,
                AvailabilitySnapshotModel.observed_at.desc(),
            )
        )
        out: dict[object, tuple[str, str | None]] = {}
        for copy_id, status, due in (await self._session.execute(stmt)).all():
            out[copy_id] = (status, due.isoformat() if due is not None else None)
        return out

    async def _covers_by_record(self, record_ids: Sequence[object]) -> dict[object, CoverView]:
        """One CoverView per record, joined via ISBN (records → isbns → covers).

        Prefers a `resolved` cover when a record has several ISBNs; returns the
        status/source even when not resolved, so the frontend can show the
        right placeholder state rather than nothing.
        """
        if not record_ids:
            return {}
        stmt = (
            select(
                IsbnModel.record_id,
                CoverModel.status,
                CoverModel.source,
                CoverModel.sha256,
            )
            .join(CoverModel, CoverModel.isbn_13 == IsbnModel.isbn)
            .where(IsbnModel.record_id.in_(record_ids))
            .distinct(IsbnModel.record_id)
            .order_by(
                IsbnModel.record_id,
                (CoverModel.status == _COVER_RESOLVED).desc(),
                CoverModel.isbn_13,
            )
        )
        out: dict[object, CoverView] = {}
        for record_id, cstatus, source, sha256 in (await self._session.execute(stmt)).all():
            url = _COVER_URL.format(sha256) if cstatus == _COVER_RESOLVED and sha256 else None
            out[record_id] = CoverView(status=cstatus, source=source, url=url)
        return out

    async def search(
        self,
        *,
        query: str,
        limit: int = 20,
        offset: int = 0,
        scope: SearchScope = SearchScope.LITERARY,
        library_branch_codes: list[str] | None = None,
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
        base_q = self._apply_scope(base_q, scope)
        # Library scope (L3): hard-filter to records held in followed branches.
        base_q = self._apply_library_scope(base_q, library_branch_codes)

        # Count first (separate query — keeps the main fetch indexable).
        total = (
            await self._session.execute(select(func.count()).select_from(base_q.subquery()))
        ).scalar_one()

        # D16: the query rank drives ordering; `relevance_score` only breaks
        # near-ties (ts_rank_cd produces many equal ranks), so a stronger
        # textual match is never displaced. titn is the final stable tiebreak.
        page_stmt = (
            base_q.options(selectinload(BibliographicRecordModel.contributors))
            .order_by(
                rank.desc(),
                BibliographicRecordModel.relevance_score.desc(),
                BibliographicRecordModel.titn.asc(),
            )
            .limit(capped_limit)
            .offset(capped_offset)
        )
        rows = (await self._session.execute(page_stmt)).scalars().all()

        items = await self._summarize(rows)

        return SearchPage(
            query=query,
            items=items,
            total=int(total),
            limit=capped_limit,
            offset=capped_offset,
        )

    async def browse(
        self,
        *,
        author: str | None = None,
        language: str | None = None,
        genre: str | None = None,
        audience: str | None = None,
        literary_form: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        available_only: bool = False,
        sort: str = "newest",
        limit: int = 20,
        offset: int = 0,
        library_branch_codes: list[str] | None = None,
    ) -> BrowsePage:
        """Faceted catalogue navigator (no query string — filters + facets).

        Unlike search, browse covers the WHOLE mirror by default: the facets
        (genre / language / audience / literary_form) give the user the
        scoping levers explicitly, and the counts double as a view of how far
        the crawl has got. Facet counts follow the standard faceted-navigation
        contract: each dimension's counts are computed with every active
        filter EXCEPT its own, so selecting a value never zeroes its siblings.
        """
        capped_limit = max(1, min(limit, _MAX_SEARCH_LIMIT))
        capped_offset = max(0, offset)

        filters = {
            "author": author,
            "language": language,
            "genre": genre,
            "audience": audience,
            "literary_form": literary_form,
        }

        def filtered(exclude: str | None = None) -> Select:  # type: ignore[type-arg]
            stmt = select(BibliographicRecordModel)
            if filters["author"] is not None and exclude != "author":
                stmt = stmt.where(
                    select(ContributorModel.record_id)
                    .where(
                        ContributorModel.record_id == BibliographicRecordModel.id,
                        ContributorModel.role == "author",
                        ContributorModel.name == filters["author"],
                    )
                    .exists()
                )
            for column_name in ("language", "genre", "audience", "literary_form"):
                value = filters[column_name]
                if value is not None and exclude != column_name:
                    stmt = stmt.where(getattr(BibliographicRecordModel, column_name) == value)
            if year_from is not None:
                stmt = stmt.where(BibliographicRecordModel.pub_year >= year_from)
            if year_to is not None:
                stmt = stmt.where(BibliographicRecordModel.pub_year <= year_to)
            # Library scope (L3) — a hard pre-filter, not a facet, so it applies
            # to every dimension's counts too (no `exclude` carve-out).
            stmt = self._apply_library_scope(stmt, library_branch_codes)
            if available_only:
                latest = (
                    select(
                        AvailabilitySnapshotModel.copy_id.label("copy_id"),
                        AvailabilitySnapshotModel.status.label("status"),
                    )
                    .distinct(AvailabilitySnapshotModel.copy_id)
                    .order_by(
                        AvailabilitySnapshotModel.copy_id,
                        AvailabilitySnapshotModel.observed_at.desc(),
                    )
                    .subquery()
                )
                stmt = stmt.where(
                    select(CopyModel.id)
                    .join(latest, latest.c.copy_id == CopyModel.id)
                    .where(
                        CopyModel.record_id == BibliographicRecordModel.id,
                        latest.c.status == AvailabilityStatus.AVAILABLE.value,
                    )
                    .exists()
                )
            return stmt

        base_q = filtered()
        total = (
            await self._session.execute(select(func.count()).select_from(base_q.subquery()))
        ).scalar_one()

        order: tuple[ColumnElement[Any], ...]
        if sort == "title":
            order = (BibliographicRecordModel.title.asc(), BibliographicRecordModel.titn.asc())
        elif sort == "newest":
            order = (
                BibliographicRecordModel.pub_year.desc().nulls_last(),
                BibliographicRecordModel.titn.desc(),
            )
        else:  # "relevance" (default) — precomputed score, titn as stable tiebreak
            order = (
                BibliographicRecordModel.relevance_score.desc(),
                BibliographicRecordModel.titn.desc(),
            )
        page_stmt = (
            base_q.options(selectinload(BibliographicRecordModel.contributors))
            .order_by(*order)
            .limit(capped_limit)
            .offset(capped_offset)
        )
        rows = (await self._session.execute(page_stmt)).scalars().all()
        items = await self._summarize(rows)

        facets: dict[str, tuple[FacetCount, ...]] = {}
        for dim in ("genre", "language", "audience", "literary_form"):
            column = getattr(BibliographicRecordModel, dim)
            eligible_ids = (
                filtered(exclude=dim).with_only_columns(BibliographicRecordModel.id).subquery()
            )
            facet_stmt = (
                select(column, func.count())
                .where(
                    BibliographicRecordModel.id.in_(select(eligible_ids.c.id)),
                    column.is_not(None),
                )
                .group_by(column)
                .order_by(func.count().desc(), column.asc())
                .limit(30)
            )
            facets[dim] = tuple(
                FacetCount(value=str(value), count=int(n))
                for value, n in (await self._session.execute(facet_stmt)).all()
            )

        return BrowsePage(
            items=items,
            total=int(total),
            limit=capped_limit,
            offset=capped_offset,
            facets=facets,
        )

    async def authors(
        self, *, query: str | None = None, limit: int = 30
    ) -> tuple[AuthorCount, ...]:
        """Author directory: distinct contributor names with record counts.

        With `query`, filters by case-insensitive substring (served by the
        existing trigram index on contributor names); without it, returns the
        most-represented authors in the mirror.
        """
        capped_limit = max(1, min(limit, _MAX_SEARCH_LIMIT))
        records = func.count(func.distinct(ContributorModel.record_id))
        stmt = (
            select(ContributorModel.name, records)
            .where(ContributorModel.role == "author")
            .group_by(ContributorModel.name)
            .order_by(records.desc(), ContributorModel.name.asc())
            .limit(capped_limit)
        )
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            stmt = stmt.where(ContributorModel.name.ilike(f"%{escaped}%", escape="\\"))
        return tuple(
            AuthorCount(name=name, records=int(n))
            for name, n in (await self._session.execute(stmt)).all()
        )

    async def semantic_search(
        self,
        *,
        query_vector: Sequence[float],
        query: str = "",
        limit: int = 20,
        offset: int = 0,
        scope: SearchScope = SearchScope.LITERARY,
        library_branch_codes: list[str] | None = None,
    ) -> SearchPage:
        """K-nearest-neighbour search over BGE-M3 embeddings (pgvector cosine).

        Ranks records by cosine distance to `query_vector` (the caller embeds
        the user's query with the same model). Only records that already have
        an embedding participate; the HNSW `vector_cosine_ops` index serves the
        ORDER BY. `scope` applies the same literary/non-fiction filter as FTS.

        `total` is the count of *embeddable* records matching the scope (the
        candidate pool), not a relevance threshold — KNN always returns its
        top-k, so `total` exists only to drive has_more/pagination symmetry.
        """
        capped_limit = max(1, min(limit, _MAX_SEARCH_LIMIT))
        capped_offset = max(0, offset)

        vector = list(query_vector)
        if not vector:
            return SearchPage(
                query=query, items=(), total=0, limit=capped_limit, offset=capped_offset
            )

        base_q = select(BibliographicRecordModel).where(
            BibliographicRecordModel.embedding.is_not(None)
        )
        base_q = self._apply_scope(base_q, scope)
        base_q = self._apply_library_scope(base_q, library_branch_codes)

        total = (
            await self._session.execute(select(func.count()).select_from(base_q.subquery()))
        ).scalar_one()

        distance = BibliographicRecordModel.embedding.cosine_distance(vector)
        # D16: cosine distance drives ordering; relevance only breaks ties.
        page_stmt = (
            base_q.options(selectinload(BibliographicRecordModel.contributors))
            .order_by(
                distance.asc(),
                BibliographicRecordModel.relevance_score.desc(),
                BibliographicRecordModel.titn.asc(),
            )
            .limit(capped_limit)
            .offset(capped_offset)
        )
        rows = (await self._session.execute(page_stmt)).scalars().all()

        items = await self._summarize(rows)
        return SearchPage(
            query=query,
            items=items,
            total=int(total),
            limit=capped_limit,
            offset=capped_offset,
        )

    async def similar_to(
        self,
        titn: Titn,
        *,
        limit: int = 8,
        scope: SearchScope = SearchScope.LITERARY,
    ) -> tuple[CatalogRecordSummary, ...]:
        """Records nearest to `titn` in embedding space ("más como este").

        Uses the record's *stored* vector (no model call needed), so this is a
        pure pgvector KNN. Excludes the record itself. Returns an empty tuple
        when the record is unknown or not yet embedded.
        """
        capped_limit = max(1, min(limit, _MAX_SEARCH_LIMIT))

        anchor = (
            await self._session.execute(
                select(BibliographicRecordModel.id, BibliographicRecordModel.embedding).where(
                    BibliographicRecordModel.titn == int(titn)
                )
            )
        ).first()
        if anchor is None or anchor.embedding is None:
            return ()

        base_q = select(BibliographicRecordModel).where(
            BibliographicRecordModel.embedding.is_not(None),
            BibliographicRecordModel.id != anchor.id,
        )
        base_q = self._apply_scope(base_q, scope)

        distance = BibliographicRecordModel.embedding.cosine_distance(anchor.embedding)
        stmt = (
            base_q.options(selectinload(BibliographicRecordModel.contributors))
            .order_by(distance.asc(), BibliographicRecordModel.titn.asc())
            .limit(capped_limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return await self._summarize(rows)

    async def summaries_by_record_ids(
        self, record_ids: Sequence[object]
    ) -> dict[object, CatalogRecordSummary]:
        """Map record id → enriched summary (cover + availability + copies).

        A cross-context read helper: other contexts (e.g. the reading-history
        shelf) hold catalogue record ids and need the same display projection
        search uses, without duplicating the cover/availability joins. Keyed by
        record id for easy join-back on the caller's side.
        """
        ids = list(record_ids)
        if not ids:
            return {}
        stmt = (
            select(BibliographicRecordModel)
            .where(BibliographicRecordModel.id.in_(ids))
            .options(selectinload(BibliographicRecordModel.contributors))
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        summaries = await self._summarize(rows)
        return {row.id: summary for row, summary in zip(rows, summaries, strict=True)}

    @staticmethod
    def _apply_scope(stmt: _SelectT, scope: SearchScope) -> _SelectT:
        """Apply the default literary/non-fiction visibility filter.

        Shared by FTS + semantic search so both honour the same `scope`
        semantics: LITERARY hides confidently children's/youth or non-fiction
        records; ALL skips the filter.
        """
        if scope is SearchScope.LITERARY:
            return stmt.where(
                BibliographicRecordModel.audience.in_(default_scope_audiences()),
                BibliographicRecordModel.literary_form.in_(default_scope_forms()),
            )
        return stmt

    @staticmethod
    def _apply_library_scope(stmt: _SelectT, branch_codes: list[str] | None) -> _SelectT:
        """Hard-filter to records held in a set of branches (Libraries L3).

        ``branch_codes=None`` is the full catalogue (no filter). Otherwise keep
        only records with at least one *active* copy in one of those branches —
        the same EXISTS shape the availability filter uses. An empty list would
        match nothing, so callers pass ``None`` (not ``[]``) for "no scope".
        """
        if branch_codes is None:
            return stmt
        return stmt.where(
            select(CopyModel.id)
            .where(
                CopyModel.record_id == BibliographicRecordModel.id,
                CopyModel.is_active.is_(True),
                CopyModel.branch_code.in_(branch_codes),
            )
            .exists()
        )

    async def _summarize(
        self, rows: Sequence[BibliographicRecordModel]
    ) -> tuple[CatalogRecordSummary, ...]:
        """Enrich a page of records into summaries (copies + availability + cover).

        Shared by FTS search, semantic search, and "more like this" so the
        per-row copies-count, available-now count, and cover join are written
        once. Preserves the input row order (the caller's relevance order).
        """
        ids = [r.id for r in rows]
        if not ids:
            return ()

        # Copies count per record (one extra round-trip; acceptable for
        # pages of up to ~100 rows).
        counts_stmt = (
            select(CopyModel.record_id, func.count(CopyModel.id))
            .where(CopyModel.record_id.in_(ids))
            .group_by(CopyModel.record_id)
        )
        copies_count_by_id = {
            rid: int(n) for rid, n in (await self._session.execute(counts_stmt)).all()
        }

        # How many copies are *available right now* per record: take each
        # copy's latest snapshot (DISTINCT ON), keep the 'available' ones,
        # count per record. Bounded to the page's copies via the subquery WHERE.
        record_copy_ids = select(CopyModel.id).where(CopyModel.record_id.in_(ids))
        latest_status = (
            select(
                AvailabilitySnapshotModel.copy_id.label("copy_id"),
                AvailabilitySnapshotModel.status.label("status"),
            )
            .where(AvailabilitySnapshotModel.copy_id.in_(record_copy_ids))
            .distinct(AvailabilitySnapshotModel.copy_id)
            .order_by(
                AvailabilitySnapshotModel.copy_id,
                AvailabilitySnapshotModel.observed_at.desc(),
            )
            .subquery()
        )
        avail_stmt = (
            select(CopyModel.record_id, func.count())
            .join(latest_status, latest_status.c.copy_id == CopyModel.id)
            .where(
                CopyModel.record_id.in_(ids),
                latest_status.c.status == AvailabilityStatus.AVAILABLE.value,
            )
            .group_by(CopyModel.record_id)
        )
        available_count_by_id = {
            rid: int(n) for rid, n in (await self._session.execute(avail_stmt)).all()
        }

        covers_by_id = await self._covers_by_record(ids)

        return tuple(
            CatalogRecordSummary(
                titn=r.titn,
                title=r.title,
                authors=tuple(c.name for c in r.contributors if c.role == "author"),
                publisher=r.publisher,
                pub_year=r.pub_year,
                copies_count=copies_count_by_id.get(r.id, 0),
                audience=r.audience,
                literary_form=r.literary_form,
                genre=r.genre,
                available_count=available_count_by_id.get(r.id, 0),
                cover=covers_by_id.get(r.id),
                relevance_score=r.relevance_score,
            )
            for r in rows
        )
