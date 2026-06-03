"""Postgres-backed `ScrapeTaskRepository`.

Uses SQLAlchemy 2.0 + asyncpg. The interesting bit is `claim_next_batch`,
which uses `SELECT ... FOR UPDATE SKIP LOCKED` so multiple workers can
share the same queue without ever fighting over the same row.

Constructors take an `AsyncSession` so the repository participates in the
caller's transaction — `mark_parsed` doesn't commit unless the caller does.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bibliohack.catalog.application.ports import (
    ScrapeTask,
    StateCounts,
    TaskState,
)
from bibliohack.catalog.domain.titn import Titn
from bibliohack.catalog.infrastructure.postgres.models import ScrapeTaskModel

# Bulk-insert chunk size. asyncpg caps prepared statements at 32_767 query
# arguments (PostgreSQL itself is 65535 but asyncpg is the tighter bound).
# SQLAlchemy emits 4 params per row (titn + the Python-side defaults for
# status / attempt_count / priority), so 8_000 rows times 4 params = 32_000
# args, safely under the cap.
_INSERT_CHUNK_SIZE = 8_000


class PostgresScrapeTaskRepository:
    """Concrete `ScrapeTaskRepository` backed by the `scrape_tasks` table."""

    def __init__(
        self, session: AsyncSession, *, refresh_interval: timedelta = timedelta(days=1)
    ) -> None:
        self._session = session
        # How far ahead a record's next availability re-scrape is scheduled
        # when it's parsed. Single interval for now; tiering (hot daily /
        # stable monthly, ARCHITECTURE §6.8) is a follow-up.
        self._refresh_interval = refresh_interval

    # ───────────────────────────────────────────────────────────
    # Seeding
    # ───────────────────────────────────────────────────────────

    async def seed_range(self, low: Titn, high: Titn) -> int:
        """Bulk-insert `discovered` rows for [low, high]; idempotent."""
        if int(low) > int(high):
            msg = f"low ({low}) must be <= high ({high})"
            raise ValueError(msg)

        inserted = 0
        for chunk_start in range(int(low), int(high) + 1, _INSERT_CHUNK_SIZE):
            chunk_end = min(chunk_start + _INSERT_CHUNK_SIZE - 1, int(high))
            stmt = (
                pg_insert(ScrapeTaskModel)
                .values(
                    [
                        {"titn": t, "status": TaskState.DISCOVERED.value}
                        for t in range(chunk_start, chunk_end + 1)
                    ]
                )
                .on_conflict_do_nothing(index_elements=["titn"])
            )
            result = await self._session.execute(stmt)
            assert isinstance(result, CursorResult)
            inserted += result.rowcount or 0
        return inserted

    async def seed_one(self, titn: Titn) -> bool:
        """Insert a single TITN as `discovered`. Idempotent."""
        stmt = (
            pg_insert(ScrapeTaskModel)
            .values(titn=int(titn), status=TaskState.DISCOVERED.value)
            .on_conflict_do_nothing(index_elements=["titn"])
        )
        result = await self._session.execute(stmt)
        assert isinstance(result, CursorResult)
        return bool(result.rowcount)

    # ───────────────────────────────────────────────────────────
    # Claiming work
    # ───────────────────────────────────────────────────────────

    async def claim_next_batch(
        self,
        *,
        limit: int = 1,
        states: Sequence[TaskState] = (TaskState.DISCOVERED,),
        require_refresh_due: bool = False,
    ) -> list[ScrapeTask]:
        """Atomic `SELECT ... FOR UPDATE SKIP LOCKED` over due rows."""
        if limit < 1:
            msg = "limit must be at least 1"
            raise ValueError(msg)
        state_values = [s.value for s in states]
        now = datetime.now(tz=UTC)

        stmt = select(ScrapeTaskModel).where(ScrapeTaskModel.status.in_(state_values))
        if require_refresh_due:
            # Refresh sweep: rows with a scheduled re-scrape that's now due,
            # oldest-due first.
            stmt = stmt.where(
                ScrapeTaskModel.refresh_due_at.is_not(None),
                ScrapeTaskModel.refresh_due_at <= now,
            ).order_by(ScrapeTaskModel.refresh_due_at.asc(), ScrapeTaskModel.titn.asc())
        else:
            # Initial crawl: due when never-retried or the backoff has elapsed.
            stmt = stmt.where(
                (ScrapeTaskModel.next_retry_at.is_(None)) | (ScrapeTaskModel.next_retry_at <= now),
            ).order_by(ScrapeTaskModel.priority.asc(), ScrapeTaskModel.titn.asc())
        stmt = stmt.limit(limit).with_for_update(skip_locked=True)
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars()]

    # ───────────────────────────────────────────────────────────
    # State transitions
    # ───────────────────────────────────────────────────────────

    async def mark_parsed(self, titn: Titn, *, source_hash: bytes) -> None:
        now = datetime.now(tz=UTC)
        await self._session.execute(
            update(ScrapeTaskModel)
            .where(ScrapeTaskModel.titn == int(titn))
            .values(
                status=TaskState.PARSED.value,
                source_hash=source_hash,
                source_seen_at=now,
                last_attempted_at=now,
                last_error=None,
                next_retry_at=None,
                refresh_due_at=now + self._refresh_interval,
                attempt_count=ScrapeTaskModel.attempt_count + 1,
            )
        )

    async def mark_not_found(self, titn: Titn) -> None:
        now = datetime.now(tz=UTC)
        await self._session.execute(
            update(ScrapeTaskModel)
            .where(ScrapeTaskModel.titn == int(titn))
            .values(
                status=TaskState.NOT_FOUND.value,
                last_attempted_at=now,
                last_error=None,
                next_retry_at=None,
                attempt_count=ScrapeTaskModel.attempt_count + 1,
            )
        )

    async def mark_skipped_non_book(self, titn: Titn) -> None:
        now = datetime.now(tz=UTC)
        await self._session.execute(
            update(ScrapeTaskModel)
            .where(ScrapeTaskModel.titn == int(titn))
            .values(
                status=TaskState.SKIPPED_NON_BOOK.value,
                last_attempted_at=now,
                last_error=None,
                next_retry_at=None,
                attempt_count=ScrapeTaskModel.attempt_count + 1,
            )
        )

    async def mark_failed(self, titn: Titn, *, error: str, next_retry_at: datetime | None) -> None:
        now = datetime.now(tz=UTC)
        await self._session.execute(
            update(ScrapeTaskModel)
            .where(ScrapeTaskModel.titn == int(titn))
            .values(
                status=TaskState.FAILED.value,
                last_attempted_at=now,
                last_error=error,
                next_retry_at=next_retry_at,
                attempt_count=ScrapeTaskModel.attempt_count + 1,
            )
        )

    # ───────────────────────────────────────────────────────────
    # Reads
    # ───────────────────────────────────────────────────────────

    async def get(self, titn: Titn) -> ScrapeTask | None:
        row = (
            await self._session.execute(
                select(ScrapeTaskModel).where(ScrapeTaskModel.titn == int(titn))
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def count_by_state(self) -> StateCounts:
        stmt = select(ScrapeTaskModel.status, func.count(ScrapeTaskModel.titn)).group_by(
            ScrapeTaskModel.status
        )
        rows = (await self._session.execute(stmt)).all()
        counts: dict[TaskState, int] = {}
        for status_value, n in rows:
            try:
                counts[TaskState(status_value)] = int(n)
            except ValueError:
                # Unknown status in the DB — surface it as TOMBSTONED so we don't crash.
                counts.setdefault(TaskState.TOMBSTONED, 0)
                counts[TaskState.TOMBSTONED] += int(n)
        return StateCounts(counts=counts)


# ─── helpers ───────────────────────────────────────────────────


def _to_domain(row: ScrapeTaskModel) -> ScrapeTask:
    return ScrapeTask(
        titn=Titn(value=row.titn),
        status=TaskState(row.status),
        source_hash=row.source_hash,
        source_seen_at=row.source_seen_at,
        attempt_count=row.attempt_count,
        last_attempted_at=row.last_attempted_at,
        next_retry_at=row.next_retry_at,
        last_error=row.last_error,
        priority=row.priority,
        refresh_due_at=row.refresh_due_at,
    )


__all__ = ["PostgresScrapeTaskRepository"]
