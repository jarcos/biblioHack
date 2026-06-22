"""`bibliohack holdings ...` CLI — branch enrichment (Libraries milestone).

Off-OPAC commands operating on the `branches` table. Currently:
`enrich-branches`, which geocodes town centroids via OpenStreetMap Nominatim so
the frontend can distance-sort branches for the proximity picker.
"""

from __future__ import annotations

import asyncio

import typer

from bibliohack.holdings.application.use_cases.enrich_branch_geo import EnrichBranchGeo
from bibliohack.holdings.infrastructure.nominatim import NominatimGeocoder
from bibliohack.holdings.infrastructure.postgres.branch_repository import PostgresBranchRepository
from bibliohack.shared.infrastructure import db_session, get_settings

holdings_app = typer.Typer(no_args_is_help=True, help="Branch / holdings commands.")


@holdings_app.command("enrich-branches")
def enrich_branches(
    max_branches: int | None = typer.Option(
        None, "--max", help="Geocode at most this many ungeocoded branches (default: all)."
    ),
    batch_size: int = typer.Option(
        50, "--batch-size", help="Ungeocoded branches read from the DB per batch."
    ),
) -> None:
    """Fill branch lat/lng from OpenStreetMap Nominatim (Libraries L0).

    For each active branch with a municipality but no coordinates yet, geocode
    the town centroid and store it. Off-OPAC — hits nominatim.openstreetmap.org
    only, paced to 1 req/s per their policy. Resumable: misses are left NULL to
    retry on a later run.

    Usage:

        bibliohack holdings enrich-branches --max 100
        bibliohack holdings enrich-branches
    """
    asyncio.run(_run_enrich_branches(max_branches, batch_size))


async def _run_enrich_branches(max_branches: int | None, batch_size: int) -> None:
    settings = get_settings()
    geocoder = NominatimGeocoder(user_agent=settings.nominatim_user_agent)
    typer.echo(f"Geocoding branches via Nominatim (max={max_branches or '∞'})…")
    typer.echo("Off-OPAC — hits nominatim.openstreetmap.org only, ≤ 1 req/s.")
    typer.echo()
    try:
        # Non-transactional session + per-batch commit so a long run persists
        # progress incrementally and resumes cleanly if interrupted.
        async with db_session() as session:
            repo = PostgresBranchRepository(session)
            use_case = EnrichBranchGeo(
                geocoder=geocoder,
                repository=repo,
                batch_size=batch_size,
                commit=session.commit,
            )
            stats = await use_case.execute(max_branches=max_branches)
    except Exception as exc:
        typer.echo(typer.style(f"Branch geocode failed: {exc}", fg=typer.colors.RED), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Branch geocode complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  scanned:   {stats.scanned:,}")
    typer.echo(f"  geocoded:  {typer.style(f'{stats.geocoded:,}', bold=True)}")
    typer.echo(f"  missed:    {stats.missed:,} (left for retry)")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
