"""Postgres-backed `ImportJobRepository`.

State transitions are conditional UPDATEs, so they're race-safe: `claim`
only succeeds while the job is still queued — a redelivered Dramatiq message
can't run the same import twice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import select, update

from bibliohack.reading_history.application.ports import ClaimedImportJob, ImportJobView
from bibliohack.reading_history.domain.import_job import ImportJobStatus
from bibliohack.reading_history.infrastructure.postgres.models import ImportJobModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from bibliohack.reading_history.application.use_cases.import_shelf import ImportStats


class PostgresImportJobRepository:
    """Concrete `ImportJobRepository` backed by SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user_id: str, filename: str | None, csv_content: str) -> str:
        job_id = uuid4()
        self._session.add(
            ImportJobModel(
                id=job_id,
                user_id=UUID(user_id),
                status=ImportJobStatus.QUEUED.value,
                filename=filename,
                csv_content=csv_content,
            )
        )
        await self._session.flush()
        return str(job_id)

    async def claim(self, job_id: str) -> ClaimedImportJob | None:
        row = (
            await self._session.execute(
                update(ImportJobModel)
                .where(
                    ImportJobModel.id == UUID(job_id),
                    ImportJobModel.status == ImportJobStatus.QUEUED.value,
                )
                .values(status=ImportJobStatus.RUNNING.value, started_at=datetime.now(UTC))
                .returning(ImportJobModel.user_id, ImportJobModel.csv_content)
            )
        ).one_or_none()
        if row is None:
            return None
        return ClaimedImportJob(user_id=str(row.user_id), csv_content=row.csv_content)

    async def mark_done(self, job_id: str, stats: ImportStats) -> None:
        await self._session.execute(
            update(ImportJobModel)
            .where(ImportJobModel.id == UUID(job_id))
            .values(
                status=ImportJobStatus.DONE.value,
                total=stats.total,
                inserted=stats.inserted,
                updated=stats.updated,
                matched_isbn=stats.matched_isbn,
                matched_title_author=stats.matched_title_author,
                unmatched=stats.unmatched,
                finished_at=datetime.now(UTC),
            )
        )

    async def mark_failed(self, job_id: str, error: str) -> None:
        await self._session.execute(
            update(ImportJobModel)
            .where(ImportJobModel.id == UUID(job_id))
            .values(
                status=ImportJobStatus.FAILED.value,
                error=error[:2000],
                finished_at=datetime.now(UTC),
            )
        )

    async def get_view(self, job_id: str, *, user_id: str) -> ImportJobView | None:
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            return None
        model = (
            await self._session.execute(
                select(ImportJobModel).where(
                    ImportJobModel.id == job_uuid,
                    ImportJobModel.user_id == UUID(user_id),
                )
            )
        ).scalar_one_or_none()
        if model is None:
            return None
        return ImportJobView(
            id=str(model.id),
            status=ImportJobStatus(model.status),
            filename=model.filename,
            total=model.total,
            inserted=model.inserted,
            updated=model.updated,
            matched_isbn=model.matched_isbn,
            matched_title_author=model.matched_title_author,
            unmatched=model.unmatched,
            error=model.error,
            created_at=model.created_at,
            finished_at=model.finished_at,
        )
