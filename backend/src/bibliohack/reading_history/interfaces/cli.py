"""Reading-history CLI: `bibliohack shelf ...`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from bibliohack.catalog.infrastructure.absysnet import GatewayConfig, ScraplingOpacGateway
from bibliohack.catalog.infrastructure.postgres import PostgresScrapeTaskRepository
from bibliohack.identity.infrastructure.postgres.user_repository import PostgresUserRepository
from bibliohack.reading_history.application.use_cases.import_shelf import ImportShelf
from bibliohack.reading_history.application.use_cases.rematch_shelf import RematchShelf
from bibliohack.reading_history.application.use_cases.resolve_unmatched_shelf import (
    DEFAULT_COOLDOWN_DAYS,
    ResolveUnmatchedShelf,
)
from bibliohack.reading_history.infrastructure.goodreads.csv_parser import parse_goodreads_csv
from bibliohack.reading_history.infrastructure.postgres.shelf_repository import (
    PostgresShelfRepository,
)
from bibliohack.shared.infrastructure import get_settings, transactional_session

shelf_app = typer.Typer(no_args_is_help=True, help="Personal bookshelf (reading history) commands.")


@shelf_app.command("import")
def import_goodreads(
    csv_path: str = typer.Argument(..., help="Path to a Goodreads library export CSV."),
    user_email: str = typer.Option(
        ...,
        "--user-email",
        help="Email of the (registered) user whose shelf receives the import.",
    ),
) -> None:
    """Import a Goodreads library export onto a user's shelf.

    Matches by ISBN-13 first, then a conservative title+author trigram
    fallback; unmatched books are still stored (re-matched for free as the
    catalogue grows). Idempotent per user: re-running updates rows in place.
    """
    path = Path(csv_path)
    if not path.is_file():
        msg = f"No such file: {csv_path}"
        raise typer.BadParameter(msg)
    asyncio.run(_run_import(path, user_email))


async def _run_import(csv_path: Path, user_email: str) -> None:
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = parse_goodreads_csv(stream)

    typer.echo(f"Parsed {len(rows)} book(s) from {csv_path.name}; matching against the catalogue…")
    async with transactional_session() as session:
        user = await PostgresUserRepository(session).get_by_email(user_email.strip().lower())
        if user is None:
            msg = f"No user registered with email {user_email!r} — register first."
            raise typer.BadParameter(msg)
        stats = await ImportShelf(repository=PostgresShelfRepository(session)).execute(
            rows, user_id=str(user.id)
        )

    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Shelf import complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  books:               {stats.total}")
    typer.echo(f"    inserted:          {stats.inserted}")
    typer.echo(f"    updated:           {stats.updated}")
    typer.echo(f"  matched (total):     {stats.matched}")
    typer.echo(f"    via ISBN:          {stats.matched_isbn}")
    typer.echo(f"    via title+author:  {stats.matched_title_author}")
    typer.echo(f"  unmatched:           {stats.unmatched}")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))


@shelf_app.command("rematch")
def rematch_shelf(
    max_rows: int | None = typer.Option(
        None,
        "--max",
        help="Re-match at most this many unmatched entries this run (default: all).",
    ),
) -> None:
    """Re-link unmatched shelf entries to records the catalogue now holds — DB-only.

    Import only matches once; entries unmatched then stay unmatched even after the
    novedades crawl (or the demand-driven fetcher's OPAC resolve → worker ingest)
    brings their record in. This re-runs the same conservative match — ISBN-13
    first, then a title+author trigram fallback — for every still-unmatched entry,
    linking the ones the mirror can now resolve. Touches the OPAC zero times;
    idempotent and safe to run periodically.

    Usage:

        bibliohack shelf rematch              # all unmatched entries
        bibliohack shelf rematch --max 500    # bounded
    """
    asyncio.run(_run_rematch(max_rows))


async def _run_rematch(max_rows: int | None) -> None:
    typer.echo(f"Re-matching unmatched shelf entries (max={max_rows or '∞'})…")
    async with transactional_session() as session:
        stats = await RematchShelf(repository=PostgresShelfRepository(session)).execute(
            max_rows=max_rows
        )

    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Shelf re-match complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  scanned:             {stats.scanned}")
    typer.echo(f"  linked (total):      {typer.style(str(stats.linked), bold=True)}")
    typer.echo(f"    via ISBN:          {stats.linked_isbn}")
    typer.echo(f"    via title+author:  {stats.linked_title_author}")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))


@shelf_app.command("resolve")
def resolve_shelf(
    max_rows: int | None = typer.Option(
        None,
        "--max",
        help="Resolve at most this many distinct unmatched books this run (default: all).",
    ),
    rate_per_second: float = typer.Option(
        1.0, "--rate", help="Polite per-second request rate to the OPAC (shared crawl budget)."
    ),
    batch_size: int = typer.Option(
        100, "--batch-size", help="Eligible books read from the DB per batch."
    ),
    cooldown_days: int = typer.Option(
        DEFAULT_COOLDOWN_DAYS,
        "--cooldown-days",
        help="Re-try a 'not held' book this many days after the last attempt.",
    ),
) -> None:
    """Ask the OPAC whether the RBPA holds unmatched shelf books (demand-driven) — on-OPAC.

    For each still-unmatched shelf book (deduped across users), query the OPAC by
    ISBN (MARC 020), then fall back to a precise title+author expert query. Held →
    seed the TITN(s) into `scrape_tasks` for the existing worker to ingest (real
    copies + availability) and mark the entries `held`; not held → mark `not_held`
    (never invents a phantom record). Bounded + polite; follow with
    `bibliohack catalog worker` to ingest, then `bibliohack shelf rematch` to link.

    Usage:

        bibliohack shelf resolve --max 50     # bounded, polite
        bibliohack shelf resolve              # all eligible

    Requires the scraper extra (see the catalog `worker` command).
    """
    asyncio.run(_run_resolve(max_rows, rate_per_second, batch_size, cooldown_days))


async def _run_resolve(
    max_rows: int | None, rate_per_second: float, batch_size: int, cooldown_days: int
) -> None:
    settings = get_settings()
    gateway = ScraplingOpacGateway(
        GatewayConfig(
            user_agent=settings.scraper_user_agent,
            rate_per_second=rate_per_second,
        )
    )
    typer.echo(
        f"Resolving unmatched shelf books against the OPAC by ISBN "
        f"(max={max_rows or '∞'}, rate={rate_per_second}/s, cooldown={cooldown_days}d)…"
    )
    typer.echo(
        "Held books are seeded for the worker; follow with `catalog worker`. Ctrl+C to stop."
    )
    typer.echo()
    try:
        # One pooled browser session spans the whole resolve run (see worker).
        async with gateway, transactional_session() as session:
            repo = PostgresShelfRepository(session)
            tasks = PostgresScrapeTaskRepository(session)
            use_case = ResolveUnmatchedShelf(
                gateway=gateway,
                repository=repo,
                tasks=tasks,
                batch_size=batch_size,
                cooldown_days=cooldown_days,
            )
            stats = await use_case.execute(max_rows=max_rows)
    except Exception as exc:
        typer.echo(typer.style(f"Shelf resolve failed: {exc}", fg=typer.colors.RED), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Shelf resolve complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  books scanned:    {stats.scanned:,}")
    typer.echo(
        f"  held:             {typer.style(f'{stats.held:,}', bold=True)} (seeded for ingest)"
    )
    typer.echo(f"  not held:         {stats.not_held:,}")
    typer.echo(f"  entries marked:   {stats.entries_marked:,}")
    typer.echo(f"  TITNs seeded:     {stats.titns_seeded:,}")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
