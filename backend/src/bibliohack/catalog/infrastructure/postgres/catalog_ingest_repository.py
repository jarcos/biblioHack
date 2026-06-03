"""Postgres-backed `CatalogIngestRepository`.

This is the single load-bearing write path for the worker. Each call:

1. Upserts the `bibliographic_records` row (by `titn`, unique index).
2. Replaces the record's child rows: `contributors`, `subjects`, `isbns`.
3. Upserts any new `branches` referenced by the parsed copies (INSERT ...
   ON CONFLICT DO NOTHING).
4. Upserts the record's `copies` by natural key (barcode, or
   (branch, signature) for barcode-less virtual copies), preserving copy
   ids; copies absent upstream are marked inactive, not deleted.
5. Records one `availability_snapshots` row per copy reflecting the
   ejemplar's loan status at observation time (M2 foundation).

Contributors / subjects / isbns are delete-then-insert (small, no dependent
rows). Copies are *upserted* rather than replaced because availability_
snapshots FK copy_id ON DELETE CASCADE — churning copy rows on each re-scrape
would wipe the availability time series, which the refresh worker depends on.

Runs inside the caller's session — `mark_parsed` on the scrape task and
this upsert ride the same transaction so they commit or roll back together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bibliohack.availability.domain.snapshot import AvailabilitySnapshot
from bibliohack.availability.domain.status import map_opac_status
from bibliohack.catalog.application.ports import IngestResult
from bibliohack.catalog.domain.literary_profile import classify_literary_profile

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
    from bibliohack.availability.application.ports import AvailabilitySnapshotRepository
    from bibliohack.catalog.infrastructure.absysnet.parser import (
        ParsedCopy,
        ParsedRecord,
    )


class PostgresCatalogIngestRepository:
    """Concrete `CatalogIngestRepository` backed by SQLAlchemy.

    Optionally takes an :class:`AvailabilitySnapshotRepository` — when
    provided, each scrape drops one snapshot per persisted copy in the
    same transaction. Passing ``None`` keeps the catalog/holdings write
    path intact but skips availability tracking (useful in tests that
    don't care about it).
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        availability_repository: AvailabilitySnapshotRepository | None = None,
    ) -> None:
        self._session = session
        self._availability = availability_repository

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

        # Classify audience + literary form from the CDU and the copy
        # signatures we have in hand (no extra I/O, no cross-context call).
        # Drives the default "literary" search/recommender scope; stored, not
        # used to discard — see catalog/domain/literary_profile.py.
        profile = classify_literary_profile(
            classification=parsed_record.classification,
            signatures=[copy.signature for copy in parsed_copies],
        )

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
                    classification=parsed_record.classification,
                    audience=profile.audience.value,
                    literary_form=profile.form.value,
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
            existing.classification = parsed_record.classification
            existing.audience = profile.audience.value
            existing.literary_form = profile.form.value
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

        # ── 4. Upsert copies for this record, preserving copy ids ─────
        # Re-scrapes (the refresh worker) must NOT churn copy rows: the
        # availability_snapshots FK is ON DELETE CASCADE, so deleting a copy
        # wipes its history. We match existing copies by their natural key —
        # barcode (the library's per-ejemplar id), or (branch_code, signature)
        # for barcode-less virtual copies — update them in place, and mark
        # copies absent upstream as inactive rather than deleting them.
        existing_copies = (
            (await self._session.execute(select(CopyModel).where(CopyModel.record_id == record_id)))
            .scalars()
            .all()
        )
        by_barcode = {c.barcode: c for c in existing_copies if c.barcode is not None}
        by_signature = {
            (c.branch_code, c.signature): c for c in existing_copies if c.barcode is None
        }
        observed_at = datetime.now(tz=UTC)
        seen_copy_ids: set[UUID] = set()
        copy_ids_with_status: list[tuple[UUID, ParsedCopy]] = []
        for copy in parsed_copies:
            match = (
                by_barcode.get(copy.barcode)
                if copy.barcode is not None
                else by_signature.get((copy.branch_code, copy.signature))
            )
            if match is not None:
                match.branch_code = copy.branch_code
                match.signature = copy.signature
                match.is_active = True
                match.last_seen_at = observed_at
                copy_id = match.id
            else:
                copy_id = uuid4()
                self._session.add(
                    CopyModel(
                        id=copy_id,
                        record_id=record_id,
                        branch_code=copy.branch_code,
                        signature=copy.signature,
                        barcode=copy.barcode,
                    )
                )
            seen_copy_ids.add(copy_id)
            copy_ids_with_status.append((copy_id, copy))

        # Copies no longer present upstream → mark inactive (keep their history).
        for stale in existing_copies:
            if stale.id not in seen_copy_ids and stale.is_active:
                stale.is_active = False
                stale.last_seen_at = observed_at

        await self._session.flush()

        # ── 5. Drop one availability snapshot per copy ────────────────
        snapshots_persisted = 0
        if self._availability is not None and copy_ids_with_status:
            snapshots = [
                AvailabilitySnapshot(
                    copy_id=cid,
                    observed_at=observed_at,
                    status=map_opac_status(copy.raw_status),
                )
                for cid, copy in copy_ids_with_status
            ]
            snapshots_persisted = await self._availability.record(snapshots)

        return IngestResult(
            record_id=str(record_id),
            titn=parsed_record.titn,
            was_new=was_new,
            copies_persisted=len(parsed_copies),
            branches_seen=len(branch_codes_seen),
            snapshots_persisted=snapshots_persisted,
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
