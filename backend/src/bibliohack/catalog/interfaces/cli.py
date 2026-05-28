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
from bibliohack.catalog.infrastructure.absysnet import (
    GatewayConfig,
    ScraplingOpacGateway,
)
from bibliohack.shared.infrastructure import get_settings

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import FetchResult
    from bibliohack.catalog.domain.titn import Titn

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
