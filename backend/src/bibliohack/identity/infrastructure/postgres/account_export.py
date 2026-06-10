"""Account data export (GDPR Art. 20) — everything we hold about one user.

A read-only cross-context projection: it SELECTs other contexts' tables
directly (like the catalogue's `summaries_by_record_ids` helper) because an
export is by definition a snapshot across the whole system. Output is a
plain JSON-serialisable dict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from bibliohack.identity.infrastructure.postgres.models import UserModel
from bibliohack.reading_history.infrastructure.postgres.models import (
    ImportJobModel,
    ShelfEntryModel,
)
from bibliohack.recommendations.infrastructure.postgres.models import RecommendationModel

if TYPE_CHECKING:
    from datetime import date, datetime

    from sqlalchemy.ext.asyncio import AsyncSession


class PostgresAccountExporter:
    """Builds the user's full data export."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def export(self, user_id: str) -> dict[str, Any]:
        uid = UUID(user_id)
        user = (
            await self._session.execute(select(UserModel).where(UserModel.id == uid))
        ).scalar_one()
        shelf = (
            (
                await self._session.execute(
                    select(ShelfEntryModel)
                    .where(ShelfEntryModel.user_id == uid)
                    .order_by(ShelfEntryModel.title)
                )
            )
            .scalars()
            .all()
        )
        jobs = (
            (
                await self._session.execute(
                    select(ImportJobModel)
                    .where(ImportJobModel.user_id == uid)
                    .order_by(ImportJobModel.created_at)
                )
            )
            .scalars()
            .all()
        )
        recommendations = (
            (
                await self._session.execute(
                    select(RecommendationModel)
                    .where(RecommendationModel.user_id == uid)
                    .order_by(RecommendationModel.score.desc())
                )
            )
            .scalars()
            .all()
        )

        return {
            "format": "bibliohack-account-export/1",
            "account": {
                "email": user.email,
                "display_name": user.display_name,
                "email_verified": user.email_verified,
                "created_at": _iso(user.created_at),
            },
            "shelf": [
                {
                    "source": entry.source,
                    "source_book_id": entry.source_book_id,
                    "title": entry.title,
                    "author": entry.author,
                    "isbn_13": entry.isbn_13,
                    "shelf": entry.shelf,
                    "rating": entry.rating,
                    "review": entry.review,
                    "date_read": _iso(entry.date_read),
                    "date_added": _iso(entry.date_added),
                    "matched_via": entry.matched_via,
                }
                for entry in shelf
            ],
            "import_jobs": [
                {
                    "filename": job.filename,
                    "status": job.status,
                    "total": job.total,
                    "created_at": _iso(job.created_at),
                    "finished_at": _iso(job.finished_at),
                }
                for job in jobs
            ],
            "recommendations": [
                {
                    "score": rec.score,
                    "rationale": rec.rationale,
                    "generated_at": _iso(rec.generated_at),
                }
                for rec in recommendations
            ],
        }


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None
