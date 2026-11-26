"""`bibliohack ops …` — crawler-plane health for the monitoring stack.

bibliohack ops check-schema                         # exit 3 on schema drift
bibliohack ops health-metrics --out /textfile/bibliohack.prom
"""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003 (typer reads the option annotation at runtime)
from typing import TYPE_CHECKING

import typer

from bibliohack.ops.application.use_cases.check_schema_revision import CheckSchemaRevision
from bibliohack.ops.application.use_cases.publish_health_metrics import PublishHealthMetrics
from bibliohack.ops.infrastructure.postgres_health_reader import PostgresHealthReader
from bibliohack.ops.infrastructure.textfile import TextfileMetricsFile
from bibliohack.shared.infrastructure import transactional_session
from bibliohack.shared.infrastructure.schema_revision import EXPECTED_SCHEMA_REVISION

if TYPE_CHECKING:
    from bibliohack.ops.application.use_cases.check_schema_revision import SchemaCheck
    from bibliohack.ops.domain.health import CrawlerHealth

# Distinct from 1 (a job's own failure) so run-job.sh can tell "refused" apart.
SCHEMA_DRIFT_EXIT_CODE = 3

ops_app = typer.Typer(no_args_is_help=True, help="Crawler-plane health checks and metrics.")


@ops_app.command("check-schema")
def check_schema() -> None:
    """Exit 3 when the database isn't on the Alembic revision this image expects."""
    result = asyncio.run(_check_schema())
    if not result.ok:
        typer.echo(typer.style(result.message, fg=typer.colors.RED), err=True)
        raise typer.Exit(code=SCHEMA_DRIFT_EXIT_CODE)
    typer.echo(result.message)


async def _check_schema() -> SchemaCheck:
    async with transactional_session() as session:
        return await CheckSchemaRevision(
            reader=PostgresHealthReader(session), expected=EXPECTED_SCHEMA_REVISION
        ).execute()


@ops_app.command("health-metrics")
def health_metrics(
    out: Path = typer.Option(
        ...,
        "--out",
        envvar="BIBLIOHACK_METRICS_FILE",
        help="Textfile for node-exporter (must already exist and be writable).",
    ),
) -> None:
    """Write the crawler's health metrics for Prometheus (node-exporter textfile)."""
    health = asyncio.run(_publish(out))
    drift = "DRIFT" if health.schema_drift else "ok"
    typer.echo(f"health metrics written to {out} (schema {drift})")


async def _publish(out: Path) -> CrawlerHealth:
    async with transactional_session() as session:
        return await PublishHealthMetrics(
            reader=PostgresHealthReader(session),
            metrics_file=TextfileMetricsFile(out),
            expected_schema_revision=EXPECTED_SCHEMA_REVISION,
        ).execute()
