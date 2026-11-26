"""The adapters satisfy the ops ports (a renamed method breaks this, not production)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bibliohack.ops.application.ports import HealthReader, MetricsFile, SchemaRevisionReader
from bibliohack.ops.infrastructure.postgres_health_reader import PostgresHealthReader
from bibliohack.ops.infrastructure.textfile import TextfileMetricsFile

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession


def test_the_postgres_reader_serves_both_reader_ports() -> None:
    reader = PostgresHealthReader(cast("AsyncSession", object()))

    assert isinstance(reader, HealthReader)
    assert isinstance(reader, SchemaRevisionReader)


def test_the_textfile_is_a_metrics_file(tmp_path: Path) -> None:
    assert isinstance(TextfileMetricsFile(tmp_path / "bibliohack.prom"), MetricsFile)
