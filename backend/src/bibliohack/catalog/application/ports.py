"""Ports — abstract interfaces between the application layer and the outside world.

The catalog use cases depend on these abstractions; the concrete implementations
(Scrapling-backed gateway, Postgres repositories) live in
`catalog/infrastructure/`. Tests substitute in-memory fakes here without
touching the domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from bibliohack.catalog.domain.titn import Titn


# ───────────────────────────────────────────────────────────────
# Errors
# ───────────────────────────────────────────────────────────────


class CatalogError(Exception):
    """Base for all catalog-application errors."""


class RecordNotFoundError(CatalogError):
    """The upstream OPAC has no record with this TITN (a 404 / "not found")."""

    def __init__(self, titn: Titn) -> None:
        super().__init__(f"No record at upstream for TITN={titn}")
        self.titn = titn


class OpacUnavailableError(CatalogError):
    """A transient upstream problem — 5xx, timeout, connection refused."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ScraperBudgetExhaustedError(CatalogError):
    """The polite-crawler daily request cap has been reached. Try again tomorrow."""


# ───────────────────────────────────────────────────────────────
# DTOs
# ───────────────────────────────────────────────────────────────


class FetchOutcome(StrEnum):
    """High-level result of a fetch attempt — used for state-machine transitions."""

    OK = "ok"
    NOT_FOUND = "not_found"
    TRANSIENT_ERROR = "transient_error"
    PERMANENT_ERROR = "permanent_error"


@dataclass(frozen=True, slots=True)
class FetchResult:
    """The bytes (or absence) we got back from the OPAC for a single TITN.

    Repository writes to `scrape_log` will consume the same shape, so the
    fields here mirror that table.
    """

    titn: Titn
    outcome: FetchOutcome
    url: str
    final_url: str
    status_code: int | None
    html: str | None
    latency_ms: int
    bytes_in: int
    error: str | None = None


# ───────────────────────────────────────────────────────────────
# Ports
# ───────────────────────────────────────────────────────────────


class OpacGateway(Protocol):
    """The catalog's only window into AbsysNET.

    Implementations are responsible for:
    - constructing the right URL (delegated to `absysnet.urls`),
    - respecting the politeness budget (per-second throttle + daily cap),
    - retrying transient failures with exponential backoff,
    - returning a `FetchResult` that downstream code can persist & parse.

    Errors are raised, not returned, when the caller cannot meaningfully
    continue — `ScraperBudgetExhaustedError` short-circuits any further
    work; `RecordNotFoundError` is fine (the state machine treats it as a
    real outcome, not a crash).
    """

    async def fetch_record(self, titn: Titn) -> FetchResult: ...
