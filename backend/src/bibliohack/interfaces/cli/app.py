"""Root typer App for the `bibliohack` CLI.

Each bounded context contributes a subcommand group. M1 ships with
`bibliohack catalog ...`; later milestones add `bibliohack holdings`,
`bibliohack recommendations`, etc.

The console_scripts entry point in pyproject.toml points at
`bibliohack.interfaces.cli.app:cli`.
"""

from __future__ import annotations

import logging

import typer

from bibliohack import __version__
from bibliohack.catalog.interfaces.cli import catalog_app
from bibliohack.covers.interfaces.cli import covers_app
from bibliohack.holdings.interfaces.cli import holdings_app
from bibliohack.reading_history.interfaces.cli import shelf_app
from bibliohack.shared.infrastructure import configure_logging, get_settings

cli = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="biblioHack — reverse catalog of the Andalusian public libraries.",
)
cli.add_typer(catalog_app, name="catalog", help="Catalog ingest and search commands.")
cli.add_typer(covers_app, name="covers", help="Cover-image resolution commands.")
cli.add_typer(holdings_app, name="holdings", help="Branch / holdings commands.")
cli.add_typer(shelf_app, name="shelf", help="Personal bookshelf (reading history) commands.")


@cli.callback()
def _bootstrap(
    *,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging."),
) -> None:
    """Initialise logging before any subcommand runs."""
    settings = get_settings()
    if verbose:
        # CLI override — bump default INFO to DEBUG.
        logging.getLogger().setLevel(logging.DEBUG)
    configure_logging(settings)


@cli.command()
def version() -> None:
    """Print the current biblioHack version."""
    typer.echo(__version__)


if __name__ == "__main__":  # pragma: no cover
    cli()
