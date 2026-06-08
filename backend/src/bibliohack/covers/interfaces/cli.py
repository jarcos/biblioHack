"""Covers CLI: `bibliohack covers ...`."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import typer

from bibliohack.covers.application.use_cases.resolve_cover import ResolveCover
from bibliohack.covers.infrastructure.images.pillow_processor import PillowImageProcessor
from bibliohack.covers.infrastructure.postgres.cover_repository import PostgresCoverRepository
from bibliohack.covers.infrastructure.providers.googlebooks import GoogleBooksCoverProvider
from bibliohack.covers.infrastructure.providers.openlibrary import OpenLibraryCoverProvider
from bibliohack.covers.infrastructure.store.filesystem import FilesystemCoverStore
from bibliohack.shared.infrastructure import get_settings, transactional_session

if TYPE_CHECKING:
    from bibliohack.covers.application.ports import CoverProvider

covers_app = typer.Typer(no_args_is_help=True, help="Cover-image resolution commands.")


@covers_app.command("resolve")
def resolve(
    limit: int = typer.Option(50, "--limit", help="Max ISBNs to resolve this run."),
) -> None:
    """Resolve covers for catalog ISBNs that don't have one yet.

    Walks the provider chain (Open Library → …), stores the first hit
    content-addressed, and records the result (RESOLVED / NOFOUND). Off the
    OPAC path. Lazy / popular-first batching is a follow-up; v1 takes the next
    `--limit` un-resolved ISBNs.

    Requires the covers extra: `uv sync --extra covers`.
    """
    asyncio.run(_run_resolve(limit))


async def _run_resolve(limit: int) -> None:
    settings = get_settings()
    # Open Library first (permissively licensed, storable); Google Books as a
    # fallback for the long tail OL doesn't have.
    providers: list[CoverProvider] = [
        OpenLibraryCoverProvider(user_agent=settings.covers_user_agent),
        GoogleBooksCoverProvider(user_agent=settings.covers_user_agent),
    ]
    processor = PillowImageProcessor()
    store = FilesystemCoverStore(settings.covers_store_path)

    async with transactional_session() as session:
        isbns = await PostgresCoverRepository(session).isbns_needing_cover(limit=limit)

    typer.echo(f"Resolving covers for {len(isbns)} ISBN(s) → {settings.covers_store_path}")
    typer.echo()
    resolved = 0
    nofound = 0
    for isbn in isbns:
        async with transactional_session() as session:
            use_case = ResolveCover(
                providers=providers,
                processor=processor,
                store=store,
                repository=PostgresCoverRepository(session),
            )
            cover = await use_case.execute(isbn)
        if cover.is_resolved:
            resolved += 1
            typer.echo(f"  ✓ {isbn} → {cover.source.value} {(cover.sha256 or '')[:12]}")
        else:
            nofound += 1
            typer.echo(f"  · {isbn} → no cover")

    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Cover resolution complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  resolved: {resolved}")
    typer.echo(f"  no cover: {nofound}")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
