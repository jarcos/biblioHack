"""FastAPI providers for the reading-history import ports.

Small provider functions so tests swap in fakes via `dependency_overrides`
without Postgres or Redis (same pattern as identity).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# Runtime imports — FastAPI evaluates dependency signatures at runtime (see
# the note in identity/interfaces/http/dependencies.py).
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from bibliohack.interfaces.http.dependencies import get_tx_session
from bibliohack.reading_history.application.ports import (  # noqa: TC001
    ImportJobQueue,
    ImportJobRepository,
)
from bibliohack.reading_history.infrastructure.dramatiq.queue import DramatiqImportJobQueue
from bibliohack.reading_history.infrastructure.postgres.import_job_repository import (
    PostgresImportJobRepository,
)


def get_import_job_repository(
    session: Annotated[AsyncSession, Depends(get_tx_session)],
) -> ImportJobRepository:
    return PostgresImportJobRepository(session)


def get_import_job_queue() -> ImportJobQueue:
    return DramatiqImportJobQueue()
