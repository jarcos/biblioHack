"""Catalog CLI subcommands: ``bibliohack catalog ...``."""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from typing import TYPE_CHECKING

import typer

from bibliohack.catalog.application.use_cases.probe_titn_range import (
    DEFAULT_HARD_MAX,
    ProbeTitnRange,
)
from bibliohack.catalog.application.use_cases.run_scrape_worker import (
    RunScrapeWorker,
    WorkerStats,
)
from bibliohack.catalog.application.use_cases.scrape_one_task import (
    ScrapeOneTask,
    ScrapeStepOutcome,
    ScrapeStepResult,
)
from bibliohack.catalog.application.use_cases.seed_discovered_tasks import (
    SeedDiscoveredTasks,
)
from bibliohack.catalog.domain.media_filter import (
    MediaTypeFilter,
    MediaTypeFilterPreset,
)
from bibliohack.catalog.domain.titn import Titn
from bibliohack.catalog.infrastructure.absysnet import (
    GatewayConfig,
    ScraplingOpacGateway,
)
from bibliohack.catalog.infrastructure.postgres import (
    PostgresScrapeTaskRepository,
)
from bibliohack.catalog.infrastructure.postgres.catalog_ingest_repository import (
    PostgresCatalogIngestRepository,
)
from bibliohack.shared.infrastructure import (
    get_settings,
    transactional_session,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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


@catalog_app.command("worker")
def worker(
    max_tasks: int | None = typer.Option(
        None,
        "--max-tasks",
        help=(
            "Stop after this many tasks (success or failure). Default: keep "
            "going until the queue empties (idle_giveup) or you Ctrl+C."
        ),
    ),
    idle_giveup: int = typer.Option(
        5,
        "--idle-giveup",
        help="Stop after this many consecutive empty claims (queue exhausted).",
    ),
    rate_per_second: float = typer.Option(
        1.0,
        "--rate",
        help="Polite per-second request rate to the upstream OPAC.",
    ),
    filter_preset: MediaTypeFilterPreset = typer.Option(  # noqa: B008
        MediaTypeFilterPreset.BOOK,
        "--filter",
        help=(
            "Which media types to persist. 'book' (default) = printed + "
            "electronic monographs. 'book+audio' also keeps audiobook "
            "monographs. 'monograph' = any record type as long as it's a "
            "monograph (no magazines / serials). 'all' = no filter."
        ),
    ),
) -> None:
    """Run the scrape worker — fetch, parse, and persist `discovered` tasks.

    Loops over ScrapeOneTask: each iteration claims one task atomically,
    fetches its HTML, parses it, persists the record + copies + branches,
    transitions the task to `parsed`. Records that don't match the
    `--filter` policy (magazines, CDs, etc.) are marked `skipped_non_book`
    so we don't fetch them again. Ctrl+C requests a graceful shutdown.

    Usage:

        bibliohack catalog worker --max-tasks 10        # smoke
        bibliohack catalog worker                       # long-running
        bibliohack catalog worker --filter all          # ingest everything
        bibliohack catalog worker --filter book+audio   # books + audiobooks

    Requires the scraper extra: `uv sync --extra scraper` and
    `make scraper-install-browsers` for the Camoufox + Chromium binaries.
    """
    media_filter = MediaTypeFilter.from_preset(filter_preset)
    asyncio.run(_run_worker(max_tasks, idle_giveup, rate_per_second, media_filter))


async def _run_worker(
    max_tasks: int | None,
    idle_giveup: int,
    rate_per_second: float,
    media_filter: MediaTypeFilter,
) -> None:
    # Build ONE gateway shared across all steps so the throttle's token
    # bucket actually does its job across requests.
    settings = get_settings()
    gateway = ScraplingOpacGateway(
        GatewayConfig(
            user_agent=settings.scraper_user_agent,
            rate_per_second=rate_per_second,
        )
    )

    # Each iteration opens a fresh transactional session so a single bad
    # task can't poison the entire run — failures roll back just that step.
    async def step_factory() -> AsyncIterator[ScrapeOneTask]:
        async with transactional_session() as session:
            yield ScrapeOneTask(
                task_repository=PostgresScrapeTaskRepository(session),
                ingest_repository=PostgresCatalogIngestRepository(session),
                gateway=gateway,
                media_filter=media_filter,
            )

    worker_run = RunScrapeWorker(
        step_factory=step_factory,
        max_tasks=max_tasks,
        idle_giveup=idle_giveup,
    )

    # Graceful shutdown on SIGINT (Ctrl+C) / SIGTERM. The signal handler
    # only flips the control flag; the in-flight step finishes first.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):  # not available on Windows
            loop.add_signal_handler(sig, worker_run.control.request_stop)

    typer.echo(
        f"Starting worker — max_tasks={max_tasks or '∞'}, "
        f"rate={rate_per_second}/s, idle_giveup={idle_giveup}"
    )
    typer.echo("Each line below is one task. Ctrl+C for graceful shutdown.")
    typer.echo()

    step_counter = [0]

    def _on_step(result: ScrapeStepResult) -> None:
        if result.outcome is ScrapeStepOutcome.NO_WORK:
            return
        step_counter[0] += 1
        marker = {
            ScrapeStepOutcome.PERSISTED: typer.style("✓", fg=typer.colors.GREEN),
            ScrapeStepOutcome.NOT_FOUND: typer.style("✗", fg=typer.colors.YELLOW),
            ScrapeStepOutcome.PERMANENT_ERROR: typer.style("!", fg=typer.colors.RED),
            ScrapeStepOutcome.TRANSIENT_ERROR: typer.style("?", fg=typer.colors.MAGENTA),
            ScrapeStepOutcome.SKIPPED_NON_BOOK: typer.style("~", fg=typer.colors.CYAN),
        }.get(result.outcome, "?")
        suffix = f" — {result.error}" if result.error else ""
        typer.echo(
            f"[{step_counter[0]:>5d}] {marker} {result.outcome.value:>17s}"
            f"  TITN={result.titn}{suffix}"
        )

    stats = await worker_run.execute(on_step=_on_step)

    _print_summary(stats)


def _print_summary(stats: WorkerStats) -> None:
    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Worker stopped.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  tasks processed:    {typer.style(f'{stats.total:,}', bold=True)}")
    typer.echo(f"    persisted:        {stats.persisted:,}")
    typer.echo(f"    not_found:        {stats.not_found:,}")
    typer.echo(f"    skipped_non_book: {stats.skipped_non_book:,}")
    typer.echo(f"    permanent errors: {stats.permanent_errors:,}")
    typer.echo(f"    transient errors: {stats.transient_errors:,}")
    typer.echo(f"  idle iterations:    {stats.no_work_hits:,}")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
