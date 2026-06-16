"""Catalog CLI subcommands: ``bibliohack catalog ...``."""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from typing import TYPE_CHECKING

import typer

from bibliohack.availability.infrastructure.postgres.availability_snapshot_repository import (
    PostgresAvailabilitySnapshotRepository,
)
from bibliohack.catalog.application.embedding_text import build_embedding_text
from bibliohack.catalog.application.ports import TaskState
from bibliohack.catalog.application.use_cases.discover_via_search import (
    DiscoverViaExpertQuery,
    novedades_expression,
)
from bibliohack.catalog.application.use_cases.probe_titn_range import (
    DEFAULT_HARD_MAX,
    ProbeTitnRange,
)
from bibliohack.catalog.application.use_cases.recompute_relevance import (
    RecomputeRelevance,
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
from bibliohack.catalog.infrastructure.embeddings.huggingface import HuggingFaceEmbedder
from bibliohack.catalog.infrastructure.postgres import (
    PostgresScrapeTaskRepository,
)
from bibliohack.catalog.infrastructure.postgres.catalog_ingest_repository import (
    PostgresCatalogIngestRepository,
)
from bibliohack.catalog.infrastructure.postgres.discovery_cursor_repository import (
    PostgresDiscoveryCursorRepository,
)
from bibliohack.catalog.infrastructure.postgres.embedding_repository import (
    PostgresEmbeddingRepository,
)
from bibliohack.catalog.infrastructure.postgres.relevance_repository import (
    PostgresRelevanceRepository,
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


@catalog_app.command("discover")
def discover(
    year_from: int = typer.Option(
        ..., "--year-from", help="Earliest publication year to include (e.g. 2024)."
    ),
    year_to: int | None = typer.Option(
        None,
        "--year-to",
        help="Latest publication year (inclusive). Omit for 'since year-from'.",
    ),
    max_results: int = typer.Option(
        200,
        "--max-results",
        help="TITNs to collect this run (the slice size; cursor advances by it).",
    ),
    rate_per_second: float = typer.Option(
        1.0, "--rate", help="Polite per-second request rate to the OPAC."
    ),
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Restart pagination from the top (ignore the saved cursor).",
    ),
) -> None:
    """Seed `scrape_tasks` from a publication-year ("novedades") expert query.

    Runs the AbsysNET expert query `@fepu>=year` and seeds the result TITNs as
    `discovered`. Pagination is **resumable**: a persisted cursor records how
    far we've gone, so each run advances `--max-results` deeper through the
    result set (~55k for 2024+) rather than re-scanning the top. Follow with
    `bibliohack catalog worker` to ingest — recent records skew literary, so
    this fills the catalogue with novels rather than the institutional backlog.

    Usage:

        bibliohack catalog discover --year-from 2024 --max-results 200
        bibliohack catalog discover --year-from 2024 --reset   # from the top

    Requires the scraper extra (see `worker`).
    """
    expression = novedades_expression(year_from=year_from, year_to=year_to)
    asyncio.run(_run_discover(expression, max_results, rate_per_second, reset=reset))


async def _run_discover(
    expression: str, max_results: int, rate_per_second: float, *, reset: bool = False
) -> None:
    settings = get_settings()
    gateway = ScraplingOpacGateway(
        GatewayConfig(
            user_agent=settings.scraper_user_agent,
            rate_per_second=rate_per_second,
        )
    )
    typer.echo(f"Discovering via expert query: {expression}  (max_results={max_results})")
    typer.echo("Resumable pagination — follow with `catalog worker` to ingest.")
    typer.echo()
    try:
        # One pooled browser session spans the whole discovery run (amortises
        # the Camoufox launch across every paginated search page).
        async with gateway, transactional_session() as session:
            tasks = PostgresScrapeTaskRepository(session)
            cursors = PostgresDiscoveryCursorRepository(session)
            use_case = DiscoverViaExpertQuery(gateway=gateway, tasks=tasks, cursors=cursors)
            result = await use_case.execute(expression, max_results=max_results, reset=reset)
    except Exception as exc:
        typer.echo(typer.style(f"Discovery failed: {exc}", fg=typer.colors.RED), err=True)
        raise typer.Exit(code=1) from exc

    pct = f"{100 * result.next_offset / result.total:.1f}%" if result.total else "?"
    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Discovery complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  query:         {expression}")
    typer.echo(f"  TITNs found:   {result.titns_found:,}")
    typer.echo(f"  newly seeded:  {typer.style(f'{result.seeded:,}', bold=True)}")
    typer.echo(f"  already known: {result.titns_found - result.seeded:,}")
    typer.echo(
        f"  cursor:        {result.start_offset:,} → {result.next_offset:,}"
        f" of {result.total:,} ({pct})"
        if result.total is not None
        else f"  cursor:        {result.start_offset:,} → {result.next_offset:,}"
    )
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
    filter_preset: MediaTypeFilterPreset = typer.Option(
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
            availability_repo = PostgresAvailabilitySnapshotRepository(session)
            ingest_repo = PostgresCatalogIngestRepository(
                session, availability_repository=availability_repo
            )
            yield ScrapeOneTask(
                task_repository=PostgresScrapeTaskRepository(session),
                ingest_repository=ingest_repo,
                gateway=gateway,
                media_filter=media_filter,
                session=session,
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

    # One pooled browser session spans the whole worker run — the launch cost
    # is paid once, not once per record (the throttle still gates each fetch).
    async with gateway:
        stats = await worker_run.execute(on_step=_on_step)

    _print_summary(stats)


@catalog_app.command("refresh")
def refresh(
    max_tasks: int | None = typer.Option(
        None, "--max-tasks", help="Stop after this many records (default: until none are due)."
    ),
    idle_giveup: int = typer.Option(
        3, "--idle-giveup", help="Stop after this many consecutive empty claims (nothing due)."
    ),
    rate_per_second: float = typer.Option(
        1.0, "--rate", help="Polite per-second request rate to the OPAC."
    ),
) -> None:
    """Re-scrape records whose availability is due, appending fresh snapshots.

    Claims `parsed` records with `refresh_due_at` in the past and re-scrapes
    them. Copy ids are preserved across re-scrapes, so each run appends one
    availability snapshot per copy — the time-series behind the "on shelf
    now" badges. Records are rescheduled for their next refresh on success.

    Usage:

        bibliohack catalog refresh                  # sweep all due records
        bibliohack catalog refresh --max-tasks 50   # bounded

    Requires the scraper extra (see `worker`).
    """
    asyncio.run(_run_refresh(max_tasks, idle_giveup, rate_per_second))


async def _run_refresh(max_tasks: int | None, idle_giveup: int, rate_per_second: float) -> None:
    settings = get_settings()
    gateway = ScraplingOpacGateway(
        GatewayConfig(
            user_agent=settings.scraper_user_agent,
            rate_per_second=rate_per_second,
        )
    )

    async def step_factory() -> AsyncIterator[ScrapeOneTask]:
        async with transactional_session() as session:
            availability_repo = PostgresAvailabilitySnapshotRepository(session)
            ingest_repo = PostgresCatalogIngestRepository(
                session, availability_repository=availability_repo
            )
            yield ScrapeOneTask(
                task_repository=PostgresScrapeTaskRepository(session),
                ingest_repository=ingest_repo,
                gateway=gateway,
                claim_states=(TaskState.PARSED,),
                require_refresh_due=True,
                session=session,
            )

    worker_run = RunScrapeWorker(
        step_factory=step_factory,
        max_tasks=max_tasks,
        idle_giveup=idle_giveup,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker_run.control.request_stop)

    typer.echo(f"Refreshing due records — max_tasks={max_tasks or '∞'}, rate={rate_per_second}/s")
    typer.echo("Each line is one re-scraped record (fresh availability snapshot). Ctrl+C to stop.")
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
        typer.echo(
            f"[{step_counter[0]:>5d}] {marker} {result.outcome.value:>17s}  TITN={result.titn}"
        )

    # One pooled browser session spans the whole refresh run (see worker).
    async with gateway:
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
    typer.echo(f"    unexpected errors:{stats.unexpected_errors:,}")
    typer.echo(f"  idle iterations:    {stats.no_work_hits:,}")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))


@catalog_app.command("embed")
def embed(
    limit: int = typer.Option(200, "--limit", help="Max records to embed this run."),
    batch_size: int = typer.Option(16, "--batch-size", help="Texts per HuggingFace request."),
) -> None:
    """Embed catalogue records that lack a vector (BGE-M3 via HuggingFace).

    Reads records with no embedding, builds the embedding text, calls the HF
    Inference API in batches, and stores the 1024-d vectors for semantic search
    / "more like this". Off the OPAC path. Requires HUGGINGFACE_API_TOKEN.
    """
    asyncio.run(_run_embed(limit, batch_size))


async def _run_embed(limit: int, batch_size: int) -> None:
    settings = get_settings()
    if not settings.huggingface_api_token:
        typer.echo(
            typer.style("HUGGINGFACE_API_TOKEN is not set — cannot embed.", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=2)

    embedder = HuggingFaceEmbedder(
        api_token=settings.huggingface_api_token,
        endpoint=settings.huggingface_embedding_endpoint,
    )
    async with transactional_session() as session:
        to_embed = await PostgresEmbeddingRepository(session).records_needing_embedding(limit=limit)

    typer.echo(f"Embedding {len(to_embed)} record(s) via {settings.embedding_model} (HF)…")
    embedded = 0
    failed = 0
    for start in range(0, len(to_embed), batch_size):
        batch = to_embed[start : start + batch_size]
        texts = [
            build_embedding_text(
                title=r.title,
                subtitle=r.subtitle,
                authors=r.authors,
                subjects=r.subjects,
                publisher=r.publisher,
            )
            for r in batch
        ]
        try:
            # The HF call is sync (httpx); run it off the event loop.
            vectors = await asyncio.to_thread(embedder.embed_documents, texts)
        except Exception as exc:
            failed += len(batch)
            typer.echo(f"  ! batch failed ({len(batch)}): {type(exc).__name__}: {str(exc)[:120]}")
            continue
        async with transactional_session() as session:
            repo = PostgresEmbeddingRepository(session)
            for record, vector in zip(batch, vectors, strict=True):
                await repo.store_embedding(record.record_id, vector)
        embedded += len(batch)
        typer.echo(f"  ✓ embedded {embedded}/{len(to_embed)}")
        await asyncio.sleep(1.0)  # gentle pacing for the HF free tier

    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Embedding complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  embedded: {embedded}")
    typer.echo(f"  failed:   {failed}")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))


# --- relevance (Phase R) -----------------------------------------------------

relevance_app = typer.Typer(
    no_args_is_help=True,
    help="Catalogue relevance scoring (precomputed, off the OPAC path).",
)
catalog_app.add_typer(relevance_app, name="relevance")


@relevance_app.command("recompute")
def relevance_recompute(
    window_days: int = typer.Option(
        90,
        "--window-days",
        help="Trailing availability window (days) the demand signal reads.",
    ),
) -> None:
    """Recompute `relevance_score` for every catalogue record.

    Pure DB compute over the availability time-series + holdings: gathers raw
    per-record signals, derives corpus-wide normalisation bounds, blends the
    four components (demand / holdings / recency / completeness), and writes the
    scores + per-component breakdown back. Runs nightly on the crawler plane.
    """
    asyncio.run(_run_relevance_recompute(window_days))


async def _run_relevance_recompute(window_days: int) -> None:
    typer.echo(f"Recomputing catalogue relevance (trailing {window_days}d window)…")
    async with transactional_session() as session:
        use_case = RecomputeRelevance(repo=PostgresRelevanceRepository(session))
        summary = await use_case.execute(window_days=window_days)

    typer.echo()
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
    typer.echo(typer.style("Relevance recompute complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  scored:     {summary.scored}")
    typer.echo(f"  written:    {summary.written}")
    typer.echo(f"  cold-start: {summary.cold_start} (no availability history → neutral demand)")
    typer.echo(typer.style("=" * 60, fg=typer.colors.BLUE))
