"""Ports of the ops context: where health facts come from and where they go."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from bibliohack.ops.domain.health import CursorProgress


class SchemaRevisionReader(Protocol):
    """The Alembic revision the database is on."""

    async def schema_revision(self) -> str | None:
        """The database's revision, or None when it has none (or it can't be read)."""
        ...


class HealthReader(SchemaRevisionReader, Protocol):
    """Read-only health facts about the crawler plane. Each one fails soft to "unknown"."""

    async def last_availability_snapshot_at(self) -> datetime | None: ...

    async def last_relevance_update_at(self) -> datetime | None: ...

    async def scrape_failures_since(self, since: datetime) -> int | None: ...

    async def discovery_cursors(self) -> list[CursorProgress]: ...

    async def record_counts(self) -> tuple[int, int] | None:
        """(records, records with an embedding). Expensive: a full scan."""
        ...


class MetricsFile(Protocol):
    """The file Prometheus reads (node-exporter textfile collector)."""

    def read(self) -> str | None:
        """Its current content, or None if it doesn't exist."""
        ...

    def write(self, content: str) -> None: ...
