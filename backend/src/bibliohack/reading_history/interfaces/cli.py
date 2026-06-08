"""Reading-history CLI: `bibliohack shelf ...`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from bibliohack.reading_history.application.use_cases.import_shelf import ImportShelf
from bibliohack.reading_history.infrastructure.goodreads.csv_parser import parse_goodreads_csv
from bibliohack.reading_history.infrastructure.postgres.shelf_repository import (
    PostgresShelfRepository,
)
from bibliohack.shared.infrastructure import transactional_session

shelf_app = typer.Typer(no_args_is_help=True, help="Personal bookshelf (reading history) commands.")


@shelf_app.command("import")
def import_goodreads(
    csv_path: str = typer.Argument(..., help="Path to a Goodreads library export CSV."),
) -> None:
    """Import a Goodreads library export, matching each book to the catalogue.

    Matches by ISBN-13 first, then a conservative title+author trigram
    fallback; unmatched books are still stored (re-matched for free as the
    catalogue grows). Idempotent: re-running updates rows in place.
    """
    path = Path(csv_path)
    if not path.is_file():
        msg = f"No such file: {csv_path}"
        raise typer.BadParameter(msg)
    asyncio.run(_run_import(path))


async def _run_import(csv_path: Path) -> None:
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = parse_goodreads_csv(stream)

    typer.echo(f"Parsed {len(rows)} book(s) from {csv_path.name}; matching against the catalogue…")
    async with transactional_session() as session:
        stats = await ImportShelf(repository=PostgresShelfRepository(session)).execute(rows)

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
