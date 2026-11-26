"""Postgres adapter for the crawler health facts (read-only).

A monitoring adapter: like the Grafana crawl dashboard, it reads across the
catalog and availability tables directly instead of asking each context,
because it only observes and never acts on what it reads.

Every query was timed on production (2026-11-26, 1.7M records) and runs every
10 minutes next to the crawl, so each is kept cheap:

- latest snapshot: `max(observed_at)` on the hypertable, ~1 s;
- relevance freshness: the newest `updated_at` among the 100 best-scored rows,
  read through the score index in milliseconds. A full recompute rewrites
  every row, top ones included; `max(updated_at)` over the table took 4.8 s;
- recent failures: `status = 'failed'` goes through the status index, ~0.1 s;
- record counts: a full scan (~27 s), which the use case asks for only every
  few hours.

Each fact runs in its own savepoint and reads as unknown when its query
fails: a drifted schema can break any one of them, and the drift itself must
still be reported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bibliohack.ops.domain.health import CursorProgress

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Row, TextClause
    from sqlalchemy.ext.asyncio import AsyncSession

_SCHEMA_REVISION = text("SELECT version_num FROM alembic_version LIMIT 1")
_LAST_SNAPSHOT = text("SELECT max(observed_at) FROM availability_snapshots")
_LAST_RELEVANCE = text(
    "SELECT max(updated_at) FROM "
    "(SELECT updated_at FROM record_relevance ORDER BY score DESC LIMIT 100) AS best"
)
_FAILURES_SINCE = text(
    "SELECT count(*) FROM scrape_tasks WHERE status = 'failed' AND last_attempted_at >= :since"
)
_CURSORS = text("SELECT expression, next_offset, total FROM discovery_cursors ORDER BY expression")
_RECORD_COUNTS = text("SELECT count(*), count(embedding) FROM bibliographic_records")


class PostgresHealthReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def schema_revision(self) -> str | None:
        rows = await self._rows("schema_revision", _SCHEMA_REVISION)
        return str(rows[0][0]) if rows else None

    async def last_availability_snapshot_at(self) -> datetime | None:
        value = await self._scalar("last_availability_snapshot_at", _LAST_SNAPSHOT)
        return cast("datetime | None", value)

    async def last_relevance_update_at(self) -> datetime | None:
        value = await self._scalar("last_relevance_update_at", _LAST_RELEVANCE)
        return cast("datetime | None", value)

    async def scrape_failures_since(self, since: datetime) -> int | None:
        value = await self._scalar("scrape_failures_since", _FAILURES_SINCE, since=since)
        return None if value is None else int(value)

    async def discovery_cursors(self) -> list[CursorProgress]:
        rows = await self._rows("discovery_cursors", _CURSORS) or []
        return [
            CursorProgress(expression=str(r[0]), next_offset=int(r[1]), total=r[2]) for r in rows
        ]

    async def record_counts(self) -> tuple[int, int] | None:
        rows = await self._rows("record_counts", _RECORD_COUNTS)
        return (int(rows[0][0]), int(rows[0][1])) if rows else None

    async def _scalar(self, fact: str, query: TextClause, **params: Any) -> Any:
        rows = await self._rows(fact, query, **params)
        return rows[0][0] if rows else None

    async def _rows(self, fact: str, query: TextClause, **params: Any) -> list[Row[Any]] | None:
        try:
            async with self._session.begin_nested():
                return list((await self._session.execute(query, params)).all())
        except DBAPIError as exc:
            structlog.get_logger().warning(
                "ops.health.fact_unreadable", fact=fact, error_type=type(exc.orig).__name__
            )
            return None
