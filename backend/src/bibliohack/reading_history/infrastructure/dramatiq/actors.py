"""The shelf-import actor — what the worker process executes.

Run the worker with:

    dramatiq bibliohack.reading_history.infrastructure.dramatiq.actors \
        --processes 1 --threads 1

Transaction layout matters here. Three separate sessions:

1. claim: queued → running, committed immediately (the UI sees progress and
   a crash can't leave the job claimable twice).
2. import + mark_done: one transaction — the shelf rows and the final stats
   land atomically.
3. mark_failed: its own session, because the import session is aborted by
   whatever exception got us here.

`max_retries=0`: failures are recorded on the job row (the UI's source of
truth) rather than retried blindly — a CSV that crashed the matcher once
will crash it again. Like the crawler plane, this process is not
OTel-instrumented; job health lives in `import_jobs`.
"""

from __future__ import annotations

import asyncio
import io

import dramatiq
import structlog

from bibliohack.reading_history.application.use_cases.import_shelf import ImportShelf
from bibliohack.reading_history.infrastructure.dramatiq.broker import configure_broker
from bibliohack.reading_history.infrastructure.goodreads.csv_parser import parse_goodreads_csv
from bibliohack.reading_history.infrastructure.postgres.import_job_repository import (
    PostgresImportJobRepository,
)
from bibliohack.reading_history.infrastructure.postgres.shelf_repository import (
    PostgresShelfRepository,
)
from bibliohack.shared.infrastructure import transactional_session

configure_broker()


async def process_import_job(job_id: str) -> None:
    """Claim, run and resolve one import job (see module docstring for tx layout)."""
    log = structlog.get_logger().bind(job_id=job_id)

    async with transactional_session() as session:
        claimed = await PostgresImportJobRepository(session).claim(job_id)
    if claimed is None:
        log.warning("shelf_import.job_not_claimable")
        return

    try:
        rows = parse_goodreads_csv(io.StringIO(claimed.csv_content))
        async with transactional_session() as session:
            stats = await ImportShelf(repository=PostgresShelfRepository(session)).execute(
                rows, user_id=claimed.user_id
            )
            await PostgresImportJobRepository(session).mark_done(job_id, stats)
        log.info(
            "shelf_import.done",
            total=stats.total,
            matched=stats.matched,
            unmatched=stats.unmatched,
        )
    except Exception as exc:
        log.exception("shelf_import.failed")
        async with transactional_session() as session:
            await PostgresImportJobRepository(session).mark_failed(job_id, str(exc))


@dramatiq.actor(max_retries=0)
def process_shelf_import(job_id: str) -> None:
    """Dramatiq entrypoint — sync shim over the async pipeline."""
    asyncio.run(process_import_job(job_id))
