"""Catalog CLI subcommands: ``bibliohack catalog ...``."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import typer

from bibliohack.catalog.application.use_cases.probe_titn_range import (
    DEFAULT_HARD_MAX,
    ProbeTitnRange,
)
from bibliohack.catalog.application.use_cases.seed_discovered_tasks import (
    SeedDiscoveredTasks,
)
from bibliohack.catalog.domain.titn import Titn
from bibliohack.catalog.infrastructure.absysnet import (
    GatewayConfig,
    ScraplingOpacGateway,
)
from bibliohack.catalog.infrastructure.postgres import (
    PostgresScrapeTaskRepository,
)
from bibliohack.shared.infrastructure import (
    get_settings,
    transactional_session,
)

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import FetchResult

log = logging.getLogger(__name__)

catalog_app = typer.Typer(
    no_args_is_help=True,
    help="Catalog ingest and search commands.",
)


@catalog_app.command("probe-titn-range")
def probe_titn_range(
    hard_max: int = typer.Option(
        DEFAULT_HARD_MAX,
        "--hard-max",
        help=(
            "Absolute ceiling for the search — we stop expanding above this "
            "even if records keep existing. Useful for time-boxing the probe."
        ),
    ),
    rate_per_second: float = typer.Option(
        1.0, "--rate", help="Requests per second to the OPAC (polite default)."
    ),
) -> None:
    """Discover the highest TITN present in the upstream catalog.

    Runs an exponential-expansion + binary-search probe against the OPAC,
    using at most ~25 fetches and respecting the politeness budget. Output
    can be fed straight to `bibliohack catalog seed --upper N` (next step).
    """
    settings = get_settings()
    cfg = GatewayConfig(
        user_agent=settings.scraper_user_agent,
        rate_per_second=rate_per_second,
        # Probing is one-off — bumping bursts/jitter doesn't help.
        burst=1,
        jitter_seconds=0.5,
    )
    gateway = ScraplingOpacGateway(cfg)

    async def _on_probe(titn: Titn, result: FetchResult) -> None:
        # Realtime feedback — one line per probed TITN.
        marker = {
            "ok": "✓",
            "not_found": "✗",
            "permanent_error": "!",
            "transient_error": "?",
        }.get(result.outcome.value, "?")
        typer.echo(f"  {marker} TITN={int(titn):>9d}  status={result.status_code}")

    use_case = ProbeTitnRange(gateway, hard_max=hard_max, on_probe=_on_probe)

    typer.echo(f"Probing TITN range (hard_max={hard_max:,}, rate={rate_per_second}/s)…")
    typer.echo("Each line below is one polite fetch — expect ~20 lines total.")
    typer.echo()

    try:
        result = asyncio.run(use_case.execute())
    except Exception as exc:
        # Translate the underlying error into something a user can act on.
        typer.echo(typer.style(f"\nProbe failed: {exc}", fg=typer.colors.RED), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Probe complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  highest existing TITN: {typer.style(str(result.highest_existing), bold=True)}")
    if result.lowest_missing is not None:
        typer.echo(f"  lowest missing TITN:   {result.lowest_missing}")
    else:
        typer.echo(
            typer.style(
                "  (no missing TITN found below hard_max — re-run with --hard-max higher)",
                fg=typer.colors.YELLOW,
            )
        )
    typer.echo(f"  fetches used:          {result.fetches_used}")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))


@catalog_app.command("seed")
def seed(
    low: int = typer.Option(
        1,
        "--from",
        help="Lowest TITN to seed as `discovered` (inclusive).",
    ),
    high: int = typer.Option(
        ...,
        "--to",
        help=(
            "Highest TITN to seed (inclusive). Pair with the `highest existing` "
            "output from `probe-titn-range`."
        ),
    ),
) -> None:
    """Populate `scrape_tasks` with `discovered` rows for [from, to].

    Idempotent: re-running with overlapping ranges only inserts the TITNs that
    are not already known. Bulk-inserts in 50k-row chunks so even a 2M range
    completes in seconds.

    Usage:

        bibliohack catalog seed --from 1 --to 100000        # smoke
        bibliohack catalog seed --from 1 --to 1500000       # full Andalucía
    """
    if low > high:
        typer.echo(
            typer.style(f"--from ({low}) must be <= --to ({high})", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=2)

    async def _run() -> int:
        async with transactional_session() as session:
            repo = PostgresScrapeTaskRepository(session)
            use_case = SeedDiscoveredTasks(repo)
            result = await use_case.execute(Titn(low), Titn(high))
            return result.inserted

    typer.echo(f"Seeding scrape_tasks for TITN [{low:,} .. {high:,}]…")
    range_size = high - low + 1
    try:
        inserted = asyncio.run(_run())
    except Exception as exc:
        typer.echo(typer.style(f"Seed failed: {exc}", fg=typer.colors.RED), err=True)
        raise typer.Exit(code=1) from exc

    already_known = range_size - inserted
    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Seed complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  range:         [{low:,} .. {high:,}] = {range_size:,} TITNs")
    typer.echo(f"  newly seeded:  {typer.style(f'{inserted:,}', bold=True)}")
    typer.echo(f"  already known: {already_known:,}")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
