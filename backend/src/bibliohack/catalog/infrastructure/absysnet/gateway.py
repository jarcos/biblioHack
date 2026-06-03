"""Scrapling-backed `OpacGateway` implementation.

The AbsysNET OPAC is a JavaScript-rendered SPA, so a plain `httpx` call would
return a boilerplate document with no useful content. We use Scrapling's
`StealthyFetcher` (Camoufox under the hood) which executes JS and gives us
the rendered HTML.

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

import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from bibliohack.catalog.application.ports import (
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


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    """Tunable parameters — pulled from Settings at composition time."""

    user_agent: str
    rate_per_second: float = 1.0
    burst: int = 1
    jitter_seconds: float = 0.5
    fetch_timeout_seconds: float = 20.0
    max_retries: int = 3
    backoff_base_seconds: float = 30.0
    backoff_cap_seconds: float = 1800.0
    endpoints: AbsysnetEndpoints = DEFAULT_ENDPOINTS


class ScraplingOpacGateway:
    """`OpacGateway` implementation backed by Scrapling's `StealthyFetcher`.

    Scrapling is imported lazily inside `fetch_record` so that test runs and
    the lightweight FastAPI image (which doesn't include the `[scraper]`
    extra) don't drag in Camoufox / Playwright at import time.
    """

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._throttle = TokenBucket(
            rate_per_second=config.rate_per_second,
            burst=config.burst,
            jitter_seconds=config.jitter_seconds,
        )

    async def fetch_record(self, titn: Titn) -> FetchResult:
        url = build_record_url(titn, endpoints=self._config.endpoints)

        await self._throttle.acquire()

        # Lazy import — Scrapling is in the [scraper] extra, not in core.
        # If it's missing, raise a clear actionable error rather than the
        # bare ModuleNotFoundError that bubbles up by default.
        try:
            # `import-not-found` covers dev installs without the [scraper]
            # extra; `unused-ignore` covers installs with it so mypy doesn't
            # flag the redundant suppression.
            from scrapling.fetchers import (  # type: ignore[import-not-found,unused-ignore]
                StealthyFetcher,
            )
        except ModuleNotFoundError as exc:
            msg = (
                "Scrapling is not installed in this venv. The OPAC scraper "
                "lives in the [scraper] optional extra. Run:\n"
                "  cd backend && uv sync --extra scraper\n"
                "  uv run camoufox fetch   # one-off, downloads the browser"
            )
            raise OpacUnavailableError(msg) from exc

        attempt = 0
        last_error: str | None = None
        while attempt <= self._config.max_retries:
            attempt += 1
            started = time.monotonic()
            try:
                page = await StealthyFetcher.async_fetch(
                    url,
                    headless=True,
                    network_idle=True,
                    timeout=int(self._config.fetch_timeout_seconds * 1000),
                    extra_headers={"User-Agent": self._config.user_agent},
                )
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
        """Paginate an expert-query results list, collecting up to `max_results` TITNs.

        Each page fetch goes through the same throttle as `fetch_record`, so
        discovery stays inside the politeness budget. Stops at `max_results`,
        when the OPAC reports no "Siguiente" page, or when a page yields no
        new TITNs (loop guard).
        """
        found: list[int] = []
        seen: set[int] = set()
        url: str | None = build_expert_url(expression, endpoints=self._config.endpoints)
        # ~10 results/page; cap pages with slack so a missing/looping 'next'
        # can't run forever.
        page_cap = (max_results + 9) // 10 + 2
        page = 0
        while url is not None and len(found) < max_results and page < page_cap:
            page += 1
            status, body, final_url = await self._fetch_rendered(url, label=f"search page={page}")
            if status != 200:
                log.warning("absysnet.search.bad_status status=%d page=%d", status, page)
                break
            results = parse_search_results(body)
            new = [titn for titn in results.titns if titn not in seen]
            if not new:
                break
            for titn in new:
                seen.add(titn)
                found.append(titn)
            if results.next_url is None:
                break
            url = urljoin(final_url or url, results.next_url)
        return found[:max_results]

    async def _fetch_rendered(self, url: str, *, label: str) -> tuple[int, str, str]:
        """Fetch one rendered page with retries → (status, body, final_url).

        Shares the stealth-fetch + backoff shape with `fetch_record`, but
        returns the raw status so the caller maps it. Raises
        `OpacUnavailableError` once transient retries (timeout / 5xx) are
        exhausted; a 4xx is returned, not retried.
        """
        await self._throttle.acquire()
        try:
            from scrapling.fetchers import (  # type: ignore[import-not-found,unused-ignore]
                StealthyFetcher,
            )
        except ModuleNotFoundError as exc:
            msg = (
                "Scrapling is not installed in this venv. The OPAC scraper "
                "lives in the [scraper] optional extra. Run:\n"
                "  cd backend && uv sync --extra scraper\n"
                "  uv run scrapling install   # downloads the browser"
            )
            raise OpacUnavailableError(msg) from exc

        attempt = 0
        last_error: str | None = None
        while attempt <= self._config.max_retries:
            attempt += 1
            try:
                page = await StealthyFetcher.async_fetch(
                    url,
                    headless=True,
                    network_idle=True,
                    timeout=int(self._config.fetch_timeout_seconds * 1000),
                    extra_headers={"User-Agent": self._config.user_agent},
                )
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
        import asyncio

        wait = min(
            self._config.backoff_cap_seconds,
            self._config.backoff_base_seconds * (2 ** (attempt - 1)),
        )
        log.info("absysnet.fetch.backoff", extra={"attempt": attempt, "wait_seconds": wait})
        await asyncio.sleep(wait)


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
