"""Scrapling-backed `OpacGateway` implementation, with an HTTP-first fast path.

Record pages are NOT JavaScript-rendered — verified against the live OPAC on
2026-07-02: the canonical `?TITN=N` URL serves a tiny `<meta http-equiv=
"Refresh">` page pointing at a session-tokenised URL, and *that* URL serves the
full record HTML (including the `js-TITN`/`T245` fields our parser reads)
without executing any JS. Once a session token is minted it can be reused for
subsequent `?TITN=N` requests directly — one request per record.

So `fetch_record` tries plain `httpx` first (when `GatewayConfig.http_first`
is on): ~0.3s per fetch instead of the 2.5-4.5s a Camoufox render costs,
which lets the worker actually reach the 1 req/s politeness ceiling instead
of idling under it. Any unexpected page shape or transport error falls back
to the original Scrapling browser path for that record, so upstream changes
degrade to the old (slow, working) behaviour rather than failing. The same
`TokenBucket` gates every HTTP request — this is a latency win, never a
request-rate increase.

The browser path also remains for discovery pagination (untouched) and as
the fallback fetcher.

This adapter:
- enforces the politeness budget via a `TokenBucket`,
- honours a global daily cap (counted via `scrape_log` in the next commit),
- identifies itself in `User-Agent`,
- maps Scrapling/Camoufox results onto our `FetchResult` DTO,
- distinguishes "record genuinely missing" (404 / OPAC error pane) from
  "OPAC was unreachable" (timeout / 5xx),
- raises `OpacUnavailableError` only after exponential-backoff retries fail.

A simpler `HttpxOpacGateway` is provided alongside for tests and for
contexts where JS execution isn't needed (a different AbsysNET install that
serves real HTML, or our own recorded fixtures).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx

from bibliohack.catalog.application.ports import (
    DiscoverySlice,
    FetchOutcome,
    FetchResult,
    OpacUnavailableError,
)
from bibliohack.catalog.infrastructure.absysnet.parser import parse_search_results
from bibliohack.catalog.infrastructure.absysnet.throttle import TokenBucket
from bibliohack.catalog.infrastructure.absysnet.urls import (
    DEFAULT_ENDPOINTS,
    AbsysnetEndpoints,
    build_expert_url,
    build_record_url,
)

if TYPE_CHECKING:
    from bibliohack.catalog.domain.titn import Titn

log = logging.getLogger(__name__)

# Markers we look for in the rendered HTML to decide outcome.
# Verified manually against the live OPAC in May 2026 (TITN=1 → real record;
# TITN=99999999 → "no recupera resultados (0 docs.)" pane). Update if
# upstream changes.
_NOT_FOUND_MARKERS = (
    "no recupera resultados",
    "(0 docs.)",
    "no se ha encontrado",
    "registro no encontrado",
)

# Shared, actionable error when the [scraper] extra (Scrapling + Camoufox)
# isn't installed — surfaced instead of a bare ModuleNotFoundError.
_SCRAPLING_MISSING_MSG = (
    "Scrapling is not installed in this venv. The OPAC scraper lives in the "
    "[scraper] optional extra. Run:\n"
    "  cd backend && uv sync --extra scraper\n"
    "  uv run scrapling install   # one-off, downloads the browser"
)


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    """Tunable parameters — pulled from Settings at composition time."""

    user_agent: str
    rate_per_second: float = 1.0
    burst: int = 1
    jitter_seconds: float = 0.5
    fetch_timeout_seconds: float = 20.0
    # Absolute ceiling on ONE rendered fetch, enforced with `asyncio.wait_for`
    # at the call site. `fetch_timeout_seconds` is only Playwright's own
    # navigation timeout — twice observed (2026-07-03, 2026-07-08) a retry's
    # `Page.goto` never returning at all after a previous goto timeout wedged
    # the patchright driver, hanging the whole crawl job for days. This bound
    # must comfortably exceed fetch_timeout_seconds (navigation + render +
    # network-idle wait) so it only fires on a genuinely wedged driver.
    fetch_hard_timeout_seconds: float = 120.0
    max_retries: int = 3
    backoff_base_seconds: float = 30.0
    backoff_cap_seconds: float = 1800.0
    endpoints: AbsysnetEndpoints = DEFAULT_ENDPOINTS
    # Try plain HTTP before the Camoufox render for record fetches (see module
    # docstring). Off by default so direct constructions (tests, one-off
    # probes) keep the original behaviour; the CLI wires it from
    # `Settings.scraper_http_first` (default on, kill switch SCRAPER_HTTP_FIRST).
    http_first: bool = False


class ScraplingOpacGateway:
    """`OpacGateway` implementation backed by Scrapling's `StealthyFetcher`.

    Scrapling is imported lazily inside `fetch_record` so that test runs and
    the lightweight FastAPI image (which doesn't include the `[scraper]`
    extra) don't drag in Camoufox / Playwright at import time.
    """

    def __init__(self, config: GatewayConfig, *, http_transport: Any = None) -> None:
        self._config = config
        self._throttle = TokenBucket(
            rate_per_second=config.rate_per_second,
            burst=config.burst,
            jitter_seconds=config.jitter_seconds,
        )
        # When non-None, a long-lived pooled browser session is reused by every
        # fetch in a crawl run (see `open_session`). Default off so a one-shot
        # fetch (probe / test) still works exactly as before.
        self._session: Any = None
        # Set by `async with gateway:` — pooling is WANTED but the browser is
        # launched lazily, on the first fetch that actually needs it (see
        # `_ensure_pooled_session`). With http_first on, most worker runs
        # never hit a browser fetch at all; eagerly launching in __aenter__
        # kept a full idle Camoufox stack (7+ processes) alive for every
        # hourly run, pinning the NAS CPU for nothing (observed 2026-07-13).
        self._pooling: bool = False
        # HTTP-first plumbing: a lazy httpx client (cookies persist across the
        # run) and the session-tokenised base URL minted by the first record's
        # meta-refresh hop, reused for one-request-per-record fetches after.
        # `http_transport` lets tests inject an httpx.MockTransport.
        self._http_transport = http_transport
        self._http_client: httpx.AsyncClient | None = None
        self._http_base: str | None = None

    # ── Pooled-session lifecycle ──────────────────────────────────
    # Launching Camoufox is by far the most expensive part of a fetch — far
    # more than the request itself. The hourly crawler used to pay that cost
    # once per record (each `StealthyFetcher.async_fetch` spins up and tears
    # down a browser), pinning effective throughput well under the 1 req/s
    # politeness ceiling. Opening one session for the whole run amortises the
    # launch across every record. We keep `max_pages=1` (strictly serial, a
    # single page) and the `TokenBucket` still gates every request, so
    # politeness is unchanged — this stops wasting time, it never crawls faster
    # than the budget allows.
    #
    # Since 2026-07-13 the launch is also LAZY: `async with gateway:` only
    # arms pooling; the browser starts on the first fetch that actually needs
    # it (`_ensure_pooled_session`). With http_first on, a healthy worker run
    # fetches everything over plain HTTP and never starts a browser at all.

    async def open_session(self) -> None:
        """Start a pooled browser session reused by every fetch until closed.

        Called lazily by `_ensure_pooled_session` (the normal path) but still
        safe to call directly for an eager launch. Idempotent: a no-op when a
        session is already open. Requires the ``[scraper]`` extra; raises
        ``OpacUnavailableError`` (not a bare ``ModuleNotFoundError``) if
        Scrapling is missing.
        """
        if self._session is not None:
            return
        async_session_cls = self._import_async_session()
        session = async_session_cls(
            headless=True,
            network_idle=True,
            max_pages=1,
            timeout=int(self._config.fetch_timeout_seconds * 1000),
            extra_headers={"User-Agent": self._config.user_agent},
        )
        await session.start()
        self._session = session

    async def close_session(self) -> None:
        """Close the pooled session (and HTTP client) if open. Idempotent."""
        self._pooling = False
        session = self._session
        self._session = None
        if session is not None:
            await session.close()
        client = self._http_client
        self._http_client = None
        self._http_base = None
        if client is not None:
            await client.aclose()

    async def __aenter__(self) -> ScraplingOpacGateway:
        # Enable pooling but do NOT launch the browser yet — with http_first
        # on, a run that never falls back to a browser fetch never pays for
        # (or even starts) the Camoufox stack. `_ensure_pooled_session` does
        # the actual launch on first need.
        self._pooling = True
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close_session()

    @staticmethod
    def _import_async_session() -> Any:
        try:
            from scrapling.fetchers import (  # type: ignore[import-not-found,unused-ignore]
                AsyncStealthySession,
            )
        except ModuleNotFoundError as exc:
            raise OpacUnavailableError(_SCRAPLING_MISSING_MSG) from exc
        return AsyncStealthySession

    @staticmethod
    def _import_stealthy_fetcher() -> Any:
        # `import-not-found` covers dev installs without the [scraper] extra;
        # `unused-ignore` covers installs with it so mypy doesn't flag the
        # redundant suppression.
        try:
            from scrapling.fetchers import (  # type: ignore[import-not-found,unused-ignore]
                StealthyFetcher,
            )
        except ModuleNotFoundError as exc:
            raise OpacUnavailableError(_SCRAPLING_MISSING_MSG) from exc
        return StealthyFetcher

    async def _stealth_fetch(self, url: str) -> Any:
        """Fetch one rendered page, via the pooled session if one is open.

        Falls back to a one-shot ``StealthyFetcher.async_fetch`` (a fresh
        browser per call) when no session is open — preserving the original
        behaviour for single fetches and the test doubles.
        """
        session = self._session
        if session is not None:
            return await session.fetch(
                url,
                network_idle=True,
                timeout=int(self._config.fetch_timeout_seconds * 1000),
                extra_headers={"User-Agent": self._config.user_agent},
            )
        stealthy_fetcher = self._import_stealthy_fetcher()
        return await stealthy_fetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=int(self._config.fetch_timeout_seconds * 1000),
            extra_headers={"User-Agent": self._config.user_agent},
        )

    async def _ensure_pooled_session(self) -> None:
        """Lazily launch the pooled browser on the first fetch that needs it.

        No-op unless pooling was requested (`async with gateway:`) and no
        session is open yet. A launch failure is logged, not raised — the
        fetch then runs one-shot (mirroring `_recycle_session`'s reopen
        fallback), and the next browser fetch retries the pooled launch.
        `OpacUnavailableError` (the [scraper] extra missing) still propagates:
        the one-shot path could not work either.
        """
        if not self._pooling or self._session is not None:
            return
        try:
            await self.open_session()
        except OpacUnavailableError:
            raise
        except Exception as exc:
            log.warning(
                "absysnet.session.lazy_open_failed error=%s: %s — using one-shot fetch",
                type(exc).__name__,
                exc,
            )

    async def _bounded_stealth_fetch(self, url: str) -> Any:
        """`_stealth_fetch` with a hard wall-clock bound and self-healing.

        Root cause of the 2026-07-03 and 2026-07-08 crawl-plane hangs: after
        a `Page.goto` timeout, the pooled session's single page slot can be
        left wedged — the NEXT fetch through it never returns (Playwright's
        own timeout never fires on a wedged driver connection), freezing the
        job until someone restarts the container. Two defenses:

        - `asyncio.wait_for` guarantees this coroutine returns or raises
          within `fetch_hard_timeout_seconds`, no matter what the driver does;
        - any failure (hard timeout or an ordinary render error) recycles the
          pooled session, so the caller's retry runs on a fresh browser page
          instead of the possibly-wedged one.

        `TimeoutError` propagates like any transient fetch error — the
        callers' retry loops backoff and re-attempt, then raise
        `OpacUnavailableError` when retries are exhausted.
        """
        # Lazy launch OUTSIDE the hard timeout: a (slow, NAS) browser start
        # must not eat into the fetch budget the bound was sized for.
        await self._ensure_pooled_session()
        try:
            return await asyncio.wait_for(
                self._stealth_fetch(url),
                timeout=self._config.fetch_hard_timeout_seconds,
            )
        except OpacUnavailableError:
            raise
        except TimeoutError:
            log.warning(
                "absysnet.fetch.hard_timeout after=%.0fs url=%s — recycling browser session",
                self._config.fetch_hard_timeout_seconds,
                url,
            )
            await self._recycle_session()
            raise
        except Exception:
            await self._recycle_session()
            raise

    async def _recycle_session(self) -> None:
        """Replace the pooled browser session after a failed fetch.

        No-op when no session is open (one-shot mode already gets a fresh
        browser per call). Closing a wedged session can itself hang, so the
        close is bounded too; on failure the old session object is abandoned —
        its driver process dies with the job (the run-job.sh timeout is the
        backstop) rather than blocking recovery. A reopen failure is logged,
        not raised: `_stealth_fetch` then falls back to one-shot fetches,
        which is slower but keeps the run alive.
        """
        session = self._session
        if session is None:
            return
        self._session = None
        try:
            await asyncio.wait_for(session.close(), timeout=30)
        except Exception as exc:
            log.warning(
                "absysnet.session.close_failed error=%s: %s — abandoning old session",
                type(exc).__name__,
                exc,
            )
        try:
            await self.open_session()
        except Exception as exc:
            log.warning(
                "absysnet.session.reopen_failed error=%s: %s — falling back to one-shot fetches",
                type(exc).__name__,
                exc,
            )

    # ── HTTP-first record fetch ───────────────────────────────────
    # See module docstring. Every GET goes through the same TokenBucket as the
    # browser path (the bootstrap hop costs two tokens, steady state one), so
    # the OPAC never sees more than the configured request rate.

    def _ensure_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                headers={"User-Agent": self._config.user_agent},
                timeout=self._config.fetch_timeout_seconds,
                follow_redirects=True,
                transport=self._http_transport,
            )
        return self._http_client

    async def _http_get(self, url: str) -> tuple[int, str, str]:
        """One throttled GET → (status, body, final_url).

        Bytes are decoded as UTF-8 directly (the server sends UTF-8 despite
        declaring iso-8859-1), so — unlike the browser path — no mojibake
        repair is needed or applied.
        """
        await self._throttle.acquire()
        resp = await self._ensure_http_client().get(url)
        return resp.status_code, _decode_http_body(resp), str(resp.url)

    def _classify_http(
        self, titn: Titn, status: int, body: str, final_url: str, started: float
    ) -> FetchResult | None:
        """Map an HTTP response onto a FetchResult, or None → browser fallback."""
        if status != 200:
            return None
        if _looks_like_not_found(body):
            outcome = FetchOutcome.NOT_FOUND
        elif _RECORD_VIEW_MARKER in body:
            outcome = FetchOutcome.OK
        else:
            # Meta-refresh page (stale session token) or an unknown shape.
            return None
        return FetchResult(
            titn=titn,
            outcome=outcome,
            url=build_record_url(titn, endpoints=self._config.endpoints),
            final_url=final_url,
            status_code=status,
            html=body,
            latency_ms=int((time.monotonic() - started) * 1000),
            bytes_in=len(body.encode("utf-8")),
        )

    async def _http_fetch_record(self, titn: Titn) -> FetchResult | None:
        """Fetch a record over plain HTTP. Returns None → fall back to browser."""
        started = time.monotonic()

        # Fast path: reuse the session token minted by a previous bootstrap.
        if self._http_base is not None:
            status, body, final_url = await self._http_get(f"{self._http_base}?TITN={int(titn)}")
            result = self._classify_http(titn, status, body, final_url, started)
            if result is not None:
                return result
            # Session expired (server answered with a fresh meta-refresh page)
            # or unexpected shape — drop the token and bootstrap again.
            self._http_base = None
            log.info("absysnet.http.session_expired titn=%d — re-bootstrapping", int(titn))

        # Bootstrap: canonical TITN URL → meta refresh → session-tokenised URL.
        url = build_record_url(titn, endpoints=self._config.endpoints)
        status, body, final_url = await self._http_get(url)
        if status != 200:
            return None
        match = _META_REFRESH.search(body)
        if match:
            refresh_url = urljoin(final_url, match.group(1))
            status, body, final_url = await self._http_get(refresh_url)
            if status == 200:
                self._http_base = refresh_url.split("?", 1)[0]
        return self._classify_http(titn, status, body, final_url, started)

    async def fetch_record(self, titn: Titn) -> FetchResult:
        if self._config.http_first:
            try:
                result = await self._http_fetch_record(titn)
            except httpx.HTTPError as exc:
                log.warning(
                    "absysnet.http.error titn=%d error=%s: %s — falling back to browser",
                    int(titn),
                    type(exc).__name__,
                    exc,
                )
                result = None
            if result is not None:
                return result
            log.info("absysnet.http.fallback titn=%d — using browser fetch", int(titn))
        return await self._browser_fetch_record(titn)

    async def _browser_fetch_record(self, titn: Titn) -> FetchResult:
        url = build_record_url(titn, endpoints=self._config.endpoints)

        await self._throttle.acquire()

        attempt = 0
        last_error: str | None = None
        while attempt <= self._config.max_retries:
            attempt += 1
            started = time.monotonic()
            try:
                page = await self._bounded_stealth_fetch(url)
            except OpacUnavailableError:
                raise
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                # Render the error inline — Python's stdlib logging doesn't
                # surface `extra=` fields by default, and during interactive
                # debugging we want the cause visible without configuring
                # a JSON renderer.
                log.warning(
                    "absysnet.fetch.exception titn=%d attempt=%d error=%s",
                    int(titn),
                    attempt,
                    last_error,
                )
                if attempt > self._config.max_retries:
                    break
                await self._backoff(attempt)
                continue

            latency_ms = int((time.monotonic() - started) * 1000)
            status = int(getattr(page, "status", 0))
            body = str(getattr(page, "html_content", "") or getattr(page, "body", ""))
            body = _repair_charset(body)
            final_url = str(getattr(page, "url", url))

            if status == 200:
                outcome = FetchOutcome.NOT_FOUND if _looks_like_not_found(body) else FetchOutcome.OK
                return FetchResult(
                    titn=titn,
                    outcome=outcome,
                    url=url,
                    final_url=final_url,
                    status_code=status,
                    html=body,
                    latency_ms=latency_ms,
                    bytes_in=len(body.encode("utf-8")),
                )

            if 500 <= status < 600 or status == 0:
                last_error = f"upstream status {status}"
                if attempt > self._config.max_retries:
                    break
                await self._backoff(attempt)
                continue

            # 4xx other than the "no record" page = permanent error for this TITN.
            return FetchResult(
                titn=titn,
                outcome=FetchOutcome.PERMANENT_ERROR,
                url=url,
                final_url=final_url,
                status_code=status,
                html=body,
                latency_ms=latency_ms,
                bytes_in=len(body.encode("utf-8")),
                error=f"unexpected status {status}",
            )

        # Retries exhausted without a usable response.
        msg = f"OPAC unavailable for TITN={titn}: {last_error}"
        raise OpacUnavailableError(msg)

    async def discover_titns(self, expression: str, *, max_results: int) -> list[int]:
        """Paginate from the top, collecting up to `max_results` TITNs.

        Thin wrapper over `discover_slice(start_offset=0)` — kept for callers
        that don't need the resume cursor.
        """
        slice_ = await self.discover_slice(expression, start_offset=0, max_results=max_results)
        return slice_.titns

    async def discover_slice(
        self, expression: str, *, start_offset: int = 0, max_results: int
    ) -> DiscoverySlice:
        """Paginate an expert-query results list starting at `start_offset`.

        Fetches page 1 once (to mint the session token + read the total),
        jumps to `DOC=start_offset+1` when resuming, then walks "Siguiente"
        forward collecting up to `max_results` new TITNs. Each fetch goes
        through the same throttle as `fetch_record`, so discovery stays inside
        the politeness budget. Returns the collected TITNs plus the offset to
        resume at next run (start_offset + count).
        """
        found: list[int] = []
        seen: set[int] = set()
        # ~10 results/page; cap pages with slack so a missing/looping 'next'
        # can't run forever.
        page_cap = (max_results + 9) // 10 + 2

        base = build_expert_url(expression, endpoints=self._config.endpoints)
        status, body, final_url = await self._fetch_rendered(base, label="search page=1")
        if status != 200:
            log.warning("absysnet.search.bad_status status=%d page=1", status)
            return DiscoverySlice(titns=[], next_offset=start_offset, total=None)
        first = parse_search_results(body)
        total = first.total

        # Nothing left beyond what we've already covered.
        if total is not None and start_offset >= total:
            return DiscoverySlice(titns=[], next_offset=start_offset, total=total)

        if start_offset <= 0:
            # Resume from the top: page 1's own results count.
            for titn in first.titns:
                if titn not in seen:
                    seen.add(titn)
                    found.append(titn)
            next_url = first.next_url
        elif first.next_url is None:
            # No pagination control → only one page exists; can't jump.
            return DiscoverySlice(titns=[], next_offset=start_offset, total=total)
        else:
            # Jump directly to the resume offset by rewriting the DOC= in the
            # 'Siguiente' href (which carries this session's token).
            next_url = re.sub(r"DOC=\d+", f"DOC={start_offset + 1}", first.next_url)

        page = 0
        url: str | None = urljoin(final_url or base, next_url) if next_url else None
        while url is not None and len(found) < max_results and page < page_cap:
            page += 1
            status, body, final_url = await self._fetch_rendered(url, label=f"search page+{page}")
            if status != 200:
                log.warning("absysnet.search.bad_status status=%d page+%d", status, page)
                break
            results = parse_search_results(body)
            if results.total is not None:
                total = results.total
            new = [titn for titn in results.titns if titn not in seen]
            if not new:
                break
            for titn in new:
                seen.add(titn)
                found.append(titn)
            if results.next_url is None:
                break
            url = urljoin(final_url or url, results.next_url)

        titns = found[:max_results]
        return DiscoverySlice(titns=titns, next_offset=start_offset + len(titns), total=total)

    async def _fetch_rendered(self, url: str, *, label: str) -> tuple[int, str, str]:
        """Fetch one rendered page with retries → (status, body, final_url).

        Shares the stealth-fetch + backoff shape with `fetch_record`, but
        returns the raw status so the caller maps it. Raises
        `OpacUnavailableError` once transient retries (timeout / 5xx) are
        exhausted; a 4xx is returned, not retried.
        """
        await self._throttle.acquire()

        attempt = 0
        last_error: str | None = None
        while attempt <= self._config.max_retries:
            attempt += 1
            try:
                page = await self._bounded_stealth_fetch(url)
            except OpacUnavailableError:
                raise
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "absysnet.fetch.exception %s attempt=%d error=%s", label, attempt, last_error
                )
                if attempt > self._config.max_retries:
                    break
                await self._backoff(attempt)
                continue

            status = int(getattr(page, "status", 0))
            body = _repair_charset(
                str(getattr(page, "html_content", "") or getattr(page, "body", ""))
            )
            final_url = str(getattr(page, "url", url))
            if status == 200 or 400 <= status < 500:
                return status, body, final_url
            last_error = f"upstream status {status}"
            if attempt > self._config.max_retries:
                break
            await self._backoff(attempt)
            continue

        msg = f"OPAC unavailable for {label}: {last_error}"
        raise OpacUnavailableError(msg)

    async def _backoff(self, attempt: int) -> None:
        wait = min(
            self._config.backoff_cap_seconds,
            self._config.backoff_base_seconds * (2 ** (attempt - 1)),
        )
        log.info("absysnet.fetch.backoff", extra={"attempt": attempt, "wait_seconds": wait})
        await asyncio.sleep(wait)


# A real record view carries the `js-TITN` field element our parser reads
# (`<span class="js-TITN">N</span>`); the meta-refresh bootstrap page and the
# not-found pane don't. Verified against the live OPAC 2026-07-02.
_RECORD_VIEW_MARKER = "js-TITN"

# The canonical `?TITN=N` URL answers with a client-side redirect:
#   <meta http-equiv="Refresh" content="0; URL=/…/abnetcl.cgi/{TOKEN}?ACC=161" />
# httpx doesn't follow meta refreshes (only real 3xx), so we parse it out.
_META_REFRESH = re.compile(
    r'http-equiv=["\']?refresh["\']?[^>]*?url=([^"\'>\s]+)',
    re.IGNORECASE,
)


def _decode_http_body(resp: httpx.Response) -> str:
    """Decode an OPAC response body from raw bytes.

    The server declares iso-8859-1 but actually serves UTF-8 (the same lie
    that forces `_repair_charset` on the browser path). Over plain HTTP we
    control decoding, so: try strict UTF-8 first (the truth), fall back to
    Latin-1 (which cannot fail — every byte maps) for a genuinely legacy page.
    """
    raw = resp.content
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _looks_like_not_found(html: str) -> bool:
    """Heuristic — does this rendered page say 'no records found'?"""
    if not html:
        return False
    lowered = html.lower()
    return any(marker in lowered for marker in _NOT_FOUND_MARKERS)


# AbsysNET pages declare `<meta charset=iso-8859-1>` but actually serve UTF-8.
# Chromium honours the (wrong) declaration and decodes the UTF-8 bytes as
# Latin-1, so the rendered DOM contains mojibake ("Jesús" -> "JesÃºs").
_LATIN1_DECL = re.compile(r'charset=["\']?\s*(?:iso-8859-1|latin-?1)', re.I)


def _repair_charset(html: str) -> str:
    """Undo the Latin-1-misread-of-UTF-8 mojibake on AbsysNET pages.

    Because Chromium decoded the *entire* document as Latin-1, every code
    point is <= U+00FF, so re-encoding the string as Latin-1 recovers the
    original response bytes and decoding those as UTF-8 restores the text.

    Guards keep this safe:
    - only attempt it when the page declares a Latin-1 family charset, and
    - keep the original on any Unicode error — a genuinely Latin-1 page (or
      one Chromium left with stray non-Latin-1 chars) will not round-trip as
      UTF-8, so we never corrupt correctly-decoded text.
    """
    if not html or not _LATIN1_DECL.search(html[:4096]):
        return html
    try:
        raw = html.encode("latin-1")
    except UnicodeEncodeError:
        # Document isn't uniformly Latin-1 (Chromium left genuine Unicode in
        # places) — not the simple mojibake case, leave it untouched.
        return html
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # The bibliographic text is valid UTF-8, but a stray non-UTF-8 byte
        # elsewhere in the page (typically inside an inline script) would make
        # a strict whole-document decode fail and silently leave the mojibake
        # in place. Decode leniently so the content fields are still repaired;
        # replacement chars only land on the genuinely-invalid bytes, which are
        # never in the title/author/publisher fields we parse.
        return raw.decode("utf-8", errors="replace")
