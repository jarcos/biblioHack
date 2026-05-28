"""Postgres-backed `ScrapeTaskRepository`.

Uses SQLAlchemy 2.0 + asyncpg. The interesting bit is `claim_next_batch`,
which uses `SELECT ... FOR UPDATE SKIP LOCKED` so multiple workers can
share the same queue without ever fighting over the same row.

Constructors take an `AsyncSession` so the repository participates in the
caller's transaction — `mark_parsed` doesn't commit unless the caller does.
"""

from datetime import UTC, datetime

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

# Bulk-insert chunk size — Postgres has a 65535-parameter limit per statement,
# and each row uses one parameter, so 50k leaves comfortable headroom.
_INSERT_CHUNK_SIZE = 50_000


class PostgresScrapeTaskRepository:
    """Concrete `ScrapeTaskRepository` backed by the `scrape_tasks` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        states: tuple[TaskState, ...] | list[TaskState] = (TaskState.DISCOVERED,),
    ) -> list[ScrapeTask]:
        """Atomic `SELECT ... FOR UPDATE SKIP LOCKED` over due rows."""
        if limit < 1:
            msg = "limit must be at least 1"
            raise ValueError(msg)
        state_values = [s.value for s in states]
        now = datetime.now(tz=UTC)

        # Tasks become "due" when:
        # - they're in one of the requested states,
        # - AND either next_retry_at IS NULL (never retried) or in the past.
        stmt = (
            select(ScrapeTaskModel)
            .where(
                ScrapeTaskModel.status.in_(state_values),
                (ScrapeTaskModel.next_retry_at.is_(None)) | (ScrapeTaskModel.next_retry_at <= now),
            )
            .order_by(
                ScrapeTaskModel.priority.asc(),
                ScrapeTaskModel.titn.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
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
