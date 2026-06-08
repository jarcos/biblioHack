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
    from collections.abc import Iterable, Sequence
    from datetime import datetime

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


@dataclass(frozen=True, slots=True)
class DiscoverySlice:
    """One paginated slice of an expert-query results list.

    `titns` are the results collected this run; `next_offset` is the DOC
    offset to resume at next time (start_offset + len(titns)); `total` is the
    OPAC's reported result count for the query (drives the wrap/clamp).
    """

    titns: list[int]
    next_offset: int
    total: int | None


class OpacSearchGateway(Protocol):
    """Discovery via AbsysNET's DOSEARCH / expert-query results lists.

    Kept separate from `OpacGateway` (single-record fetch) so the ingest
    worker needn't implement search, and so test stubs stay small. The
    adapter paginates the results list politely (per-second throttle) and
    returns the TITNs it found.
    """

    async def discover_titns(self, expression: str, *, max_results: int) -> list[int]:
        """Run an AbsysNET expert query (xsqf99) and return up to `max_results`
        result TITNs, paginating politely. `expression` is the raw expert
        syntax, e.g. ``"(@fepu>=2024)"`` for records published since 2024."""
        ...

    async def discover_slice(
        self, expression: str, *, start_offset: int = 0, max_results: int
    ) -> DiscoverySlice:
        """Like `discover_titns`, but resumes at `start_offset` (a DOC offset).

        The OPAC results list supports jumping directly to an arbitrary DOC
        offset within a session, so this fetches page 1 once (to mint the
        session token + read the total), jumps to `start_offset`, and walks
        forward collecting up to `max_results` TITNs. Returns the slice plus
        the offset to resume at — so a persisted cursor can march through the
        entire result set across runs."""
        ...


# ───────────────────────────────────────────────────────────────
# Embeddings — semantic search / "more like this"
# ───────────────────────────────────────────────────────────────


class Embedder(Protocol):
    """Turns text into dense vectors for semantic search.

    Synchronous: embedding is CPU-bound (no I/O), and the embedder runs as a
    batch job, so there's nothing to await. The concrete adapter (BGE-M3 via
    sentence-transformers) lives in `catalog/infrastructure/embeddings/` and is
    only loaded where the heavy `ai` extra is installed (the embedder plane),
    never in the read API.
    """

    @property
    def dimensions(self) -> int:
        """Vector size this embedder produces (1024 for BGE-M3)."""
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of record texts — one L2-normalized vector each."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query as one L2-normalized vector."""
        ...


# ───────────────────────────────────────────────────────────────
# Discovery cursor — resumable expert-query pagination
# ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DiscoveryCursor:
    """Persisted pagination state for one expert-query expression."""

    expression: str
    next_offset: int
    total: int | None = None


class DiscoveryCursorRepository(Protocol):
    """Persistence for how far each expert query has been paginated."""

    async def get(self, expression: str) -> DiscoveryCursor | None:
        """Return the saved cursor for `expression`, or None if never run."""
        ...

    async def save(self, expression: str, *, next_offset: int, total: int | None) -> None:
        """Upsert the cursor for `expression`."""
        ...


# ───────────────────────────────────────────────────────────────
# Scrape state machine — TaskState + ScrapeTaskRepository
# ───────────────────────────────────────────────────────────────


class TaskState(StrEnum):
    """Lifecycle state of a `scrape_tasks` row.

    The state machine is documented in `ARCHITECTURE.md` §6.7:

        discovered → fetched → parsed
                        │
                        ├─→ not_found        (404 / no-result page)
                        ├─→ failed           (5xx-then-retry-exhausted)
                        ├─→ skipped_non_book (record exists but is a magazine /
                        │                     audiobook / CD / etc — see media
                        │                     filter)
                        └─→ tombstoned       (manually retired)
    """

    DISCOVERED = "discovered"
    FETCHED = "fetched"
    PARSED = "parsed"
    NOT_FOUND = "not_found"
    FAILED = "failed"
    SKIPPED_NON_BOOK = "skipped_non_book"
    TOMBSTONED = "tombstoned"


@dataclass(frozen=True, slots=True)
class ScrapeTask:
    """Snapshot of one `scrape_tasks` row as seen by the application layer."""

    titn: Titn
    status: TaskState
    source_hash: bytes | None = None
    source_seen_at: datetime | None = None
    attempt_count: int = 0
    last_attempted_at: datetime | None = None
    next_retry_at: datetime | None = None
    last_error: str | None = None
    priority: int = 100
    refresh_due_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StateCounts:
    """Histogram of `scrape_tasks` by status — useful for progress dashboards."""

    counts: dict[TaskState, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def get(self, state: TaskState) -> int:
        return self.counts.get(state, 0)


class ScrapeTaskRepository(Protocol):
    """The catalog's persistence port for the discovery / refresh state machine.

    Implementations atomically claim work via `SELECT ... FOR UPDATE SKIP
    LOCKED` so multiple workers can run side-by-side without colliding.
    """

    async def seed_range(self, low: Titn, high: Titn) -> int:
        """Insert `discovered` rows for every TITN in [low, high] not yet known.

        Returns the number of NEW rows inserted (existing rows are left as-is).
        Idempotent — safe to re-run with overlapping ranges.
        """
        ...

    async def seed_one(self, titn: Titn) -> bool:
        """Insert a single TITN as `discovered` if not already present.

        Returns True if a new row was inserted, False if the row already existed.
        """
        ...

    async def claim_next_batch(
        self,
        *,
        limit: int = 1,
        states: Sequence[TaskState] = (TaskState.DISCOVERED,),
        require_refresh_due: bool = False,
    ) -> list[ScrapeTask]:
        """Atomically lock and return up to `limit` due tasks.

        Uses `SELECT ... FOR UPDATE SKIP LOCKED` so concurrent workers get
        disjoint batches. The locks release when the surrounding transaction
        commits or rolls back; callers are expected to update the rows'
        state before committing.

        `require_refresh_due=True` (the refresh worker) restricts to rows whose
        `refresh_due_at` is set and in the past, ordered oldest-due first —
        used to re-scrape already-`parsed` records so the availability
        time-series stays current.
        """
        ...

    async def mark_parsed(self, titn: Titn, *, source_hash: bytes) -> None:
        """Transition `titn` to `parsed`, recording the payload hash."""
        ...

    async def mark_not_found(self, titn: Titn) -> None:
        """Transition `titn` to `not_found` (no retries)."""
        ...

    async def mark_failed(self, titn: Titn, *, error: str, next_retry_at: datetime | None) -> None:
        """Transition `titn` to `failed` with backoff scheduling info."""
        ...

    async def mark_skipped_non_book(self, titn: Titn) -> None:
        """Transition `titn` to `skipped_non_book` (parsed but filter rejected it)."""
        ...

    async def get(self, titn: Titn) -> ScrapeTask | None:
        """Read a single task by TITN. Returns None if not yet seeded."""
        ...

    async def count_by_state(self) -> StateCounts:
        """Histogram of all `scrape_tasks` by status."""
        ...


# ───────────────────────────────────────────────────────────────
# Scrape activity log (politeness accounting)
# ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ScrapeLogEntry:
    """One row written to `scrape_log` per HTTP request to the OPAC."""

    titn: Titn | None
    url: str
    status_code: int | None
    latency_ms: int | None
    bytes_in: int | None
    error: str | None


class ScrapeLogRepository(Protocol):
    """Append-only log of HTTP requests we made. Drives daily-cap accounting."""

    async def record(self, entries: Iterable[ScrapeLogEntry]) -> None: ...

    async def requests_since(self, since: datetime) -> int:
        """How many requests have been issued since `since`. Used for the cap."""
        ...


# ───────────────────────────────────────────────────────────────
# Catalog ingest — the meat of the worker's persistence work
# ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of one persist_parsed_record call."""

    record_id: str  # UUID as string — stable across re-runs once assigned
    titn: int
    was_new: bool  # False on re-scrape
    copies_persisted: int
    branches_seen: int
    # M2 — number of availability_snapshots rows actually inserted by this
    # call. Zero when the ingest repository wasn't wired with a snapshot
    # repository (e.g. legacy tests) or when there were no copies.
    snapshots_persisted: int = 0


class CatalogReadRepository(Protocol):
    """Read-only port for the public catalog API.

    Kept separate from `CatalogIngestRepository` (the write path) so a
    light-weight read-only API container could plug in an SQLite-FTS or
    a Postgres-replica implementation without inheriting the write
    code path.
    """

    async def find_by_titn(self, titn: Titn) -> object:  # CatalogRecordView | None
        """Return the full record view for `titn`, or None if not yet scraped."""
        ...

    async def search(self, *, query: str, limit: int = 20, offset: int = 0) -> object:  # SearchPage
        """Full-text search over title + subtitle + publisher + summary.

        Uses the `spanish_unaccent` text-search configuration and the
        `fts` generated tsvector column. Empty / whitespace queries
        return an empty page rather than every record.
        """
        ...


class CatalogIngestRepository(Protocol):
    """One-call port: turn a `ParsedRecord` + `list[ParsedCopy]` into rows.

    The single method exists because every worker call needs the same atomic
    upsert across `bibliographic_records`, `contributors`, `subjects`, `isbns`,
    `branches`, `copies` — splitting them across repositories at the worker
    level would force the use case to coordinate transactions across modules.

    Implementations run everything inside the caller's session/transaction
    so a failure mid-write rolls back cleanly. Branches missing from the
    `branches` table are upserted on the fly (we discover branches as we
    discover records).
    """

    async def persist_parsed_record(
        self,
        *,
        parsed: object,  # ParsedRecord — typed loosely to avoid a circular import
        copies: object,  # list[ParsedCopy] — same reason
        source_url: str,
        source_hash: bytes,
    ) -> IngestResult: ...
