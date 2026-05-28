"""Postgres-backed `CatalogIngestRepository`.

This is the single load-bearing write path for the worker. Each call:

1. Upserts the `bibliographic_records` row (by `titn`, unique index).
2. Replaces the record's child rows: `contributors`, `subjects`, `isbns`.
3. Upserts any new `branches` referenced by the parsed copies (INSERT ...
   ON CONFLICT DO NOTHING).
4. Replaces the record's `copies` rows.

Replacement (delete-then-insert) rather than diffing is the right MVP for
M1: the upstream catalog isn't that volatile, the child counts are small
per record (≤10), and we'd rather have simple obviously-correct code than
clever diff logic that we'd want to throw away once availability tracking
(M2) gives us first-class history.

Runs inside the caller's session — `mark_parsed` on the scrape task and
this upsert ride the same transaction so they commit or roll back together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bibliohack.catalog.application.ports import IngestResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
from bibliohack.catalog.infrastructure.postgres.models import (
    BibliographicRecordModel,
    ContributorModel,
    IsbnModel,
    SubjectModel,
)
from bibliohack.holdings.infrastructure.postgres.models import BranchModel, CopyModel

if TYPE_CHECKING:
    from bibliohack.catalog.infrastructure.absysnet.parser import (
        ParsedCopy,
        ParsedRecord,
    )


class PostgresCatalogIngestRepository:
    """Concrete `CatalogIngestRepository` backed by SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def persist_parsed_record(
        self,
        *,
        parsed: object,
        copies: object,
        source_url: str,
        source_hash: bytes,
    ) -> IngestResult:
        # The Protocol uses `object` to dodge a circular import; we cast back here.
        parsed_record: ParsedRecord = parsed  # type: ignore[assignment]
        parsed_copies: list[ParsedCopy] = copies  # type: ignore[assignment]

        # `authors_text` is the denormalised author-name column that feeds
        # the generated FTS tsvector. The contributors table is still the
        # source of truth; this is just a cache so we can include authors
        # in `fts` (a generated column can only see its own row's data).
        authors_text = _join_authors(parsed_record.authors)

        # ── 1. Upsert the bibliographic record ────────────────
        existing = await self._find_record_by_titn(parsed_record.titn)
        if existing is None:
            record_id = uuid4()
            self._session.add(
                BibliographicRecordModel(
                    id=record_id,
                    titn=parsed_record.titn,
                    title=parsed_record.title,
                    subtitle=None,
                    document_type=parsed_record.document_type,
                    language=parsed_record.language,
                    pub_year=parsed_record.pub_year,
                    publisher=parsed_record.publisher,
                    summary=None,
                    source_url=source_url,
                    source_hash=source_hash,
                    authors_text=authors_text,
                )
            )
            was_new = True
        else:
            record_id = existing.id
            existing.title = parsed_record.title
            existing.document_type = parsed_record.document_type
            existing.language = parsed_record.language
            existing.pub_year = parsed_record.pub_year
            existing.publisher = parsed_record.publisher
            existing.source_url = source_url
            existing.source_hash = source_hash
            existing.authors_text = authors_text
            was_new = False

        # We need the record row visible to subsequent inserts in this
        # transaction (FK on contributors / subjects / isbns / copies).
        await self._session.flush()

        # ── 2. Replace child rows: contributors / subjects / isbns ────
        await self._replace_child_rows(record_id, parsed_record)

        # ── 3. Upsert branches referenced by the parsed copies ────────
        branch_codes_seen = await self._upsert_branches(parsed_copies)

        # ── 4. Replace copies for this record ─────────────────────────
        await self._session.execute(delete(CopyModel).where(CopyModel.record_id == record_id))
        for copy in parsed_copies:
            self._session.add(
                CopyModel(
                    id=uuid4(),
                    record_id=record_id,
                    branch_code=copy.branch_code,
                )
            )

        await self._session.flush()

        return IngestResult(
            record_id=str(record_id),
            titn=parsed_record.titn,
            was_new=was_new,
            copies_persisted=len(parsed_copies),
            branches_seen=len(branch_codes_seen),
        )

    # ───────────────────────────────────────────────────────────
    # internals
    # ───────────────────────────────────────────────────────────

    async def _find_record_by_titn(self, titn: int) -> BibliographicRecordModel | None:
        return (
            await self._session.execute(
                select(BibliographicRecordModel).where(BibliographicRecordModel.titn == titn)
            )
        ).scalar_one_or_none()

    async def _replace_child_rows(self, record_id: UUID, parsed_record: ParsedRecord) -> None:
        # Always wipe + re-insert. Counts are small (≤10 contributors,
        # ≤20 subjects, ≤2 ISBNs) so the cost is trivial vs. the clarity
        # of "the DB matches the latest scrape exactly".
        await self._session.execute(
            delete(ContributorModel).where(ContributorModel.record_id == record_id)
        )
        for order_index, name in enumerate(parsed_record.authors):
            self._session.add(
                ContributorModel(
                    id=uuid4(),
                    record_id=record_id,
                    name=name,
                    role="author",
                    order_index=order_index,
                )
            )

        await self._session.execute(delete(SubjectModel).where(SubjectModel.record_id == record_id))
        # Subjects aren't yet populated by the parser; placeholder loop here
        # for when M2/M3 wire that up.
        for subject in getattr(parsed_record, "subjects", ()):
            self._session.add(SubjectModel(record_id=record_id, subject=subject))

        await self._session.execute(delete(IsbnModel).where(IsbnModel.record_id == record_id))
        for isbn in getattr(parsed_record, "isbns", ()):
            self._session.add(IsbnModel(record_id=record_id, isbn=isbn))

    async def _upsert_branches(self, parsed_copies: list[ParsedCopy]) -> set[str]:
        # Dedup by branch_code — multiple copies may share a branch.
        by_code: dict[str, str] = {}
        for copy in parsed_copies:
            by_code.setdefault(copy.branch_code, copy.branch_name)

        if not by_code:
            return set()

        rows = [{"code": code, "name": name} for code, name in by_code.items()]
        stmt = pg_insert(BranchModel).values(rows).on_conflict_do_nothing(index_elements=["code"])
        await self._session.execute(stmt)
        return set(by_code.keys())


def _join_authors(authors: tuple[str, ...]) -> str | None:
    """Collapse the parsed author tuple into a single text blob for FTS.

    Returned value goes into `bibliographic_records.authors_text` and is
    then folded into the generated `fts` tsvector by Postgres. Returning
    `None` (rather than an empty string) for records with no authors
    keeps the column NULL-clean — `coalesce(authors_text, '')` in the
    SQL expression handles the empty case.
    """
    cleaned = tuple(name.strip() for name in authors if name and name.strip())
    if not cleaned:
        return None
    return " ".join(cleaned)
