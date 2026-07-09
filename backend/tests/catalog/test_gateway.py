"""Tests for ScraplingOpacGateway.

We don't drive Scrapling for real here — that would require Camoufox and a
running OPAC. Instead we monkeypatch the lazy `StealthyFetcher.async_fetch`
import to return fake responses, which lets us exhaustively cover the state
machine (OK / NOT_FOUND / PERMANENT / retry-then-fail).

Integration tests against the live OPAC live in `tests/catalog/integration/`
and are skipped by default.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import ClassVar

import httpx
import pytest

from bibliohack.catalog.application.ports import FetchOutcome, OpacUnavailableError
from bibliohack.catalog.domain.titn import Titn
from bibliohack.catalog.infrastructure.absysnet.gateway import (
    GatewayConfig,
    ScraplingOpacGateway,
)

# ───────────────────────────────────────────────────────────────
# Test doubles
# ───────────────────────────────────────────────────────────────


@dataclass
class FakePage:
    """Matches the duck-typed interface our gateway reads from Scrapling pages."""

    status: int
    html_content: str
    url: str = "https://example.test/cgi-bin/abnetcl?TITN=1"


class FakeFetcher:
    """Stand-in for Scrapling's `StealthyFetcher` — returns scripted responses."""

    def __init__(
        self,
        responses: list[FakePage | Exception],
    ) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def async_fetch(self, url: str, **_kwargs: object) -> FakePage:
        self.calls.append(url)
        if not self._responses:
            msg = "FakeFetcher ran out of scripted responses"
            raise RuntimeError(msg)
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class FakeAsyncSession:
    """Stand-in for Scrapling's `AsyncStealthySession` (pooled browser).

    Records construction kwargs, start/close counts, and routed fetches so a
    test can assert the gateway opens exactly one session per run, reuses it
    for every fetch, and closes it afterwards — without launching Camoufox.

    Instances register themselves in the class-level `instances` list (clear
    it at the top of each test).
    """

    instances: ClassVar[list[FakeAsyncSession]] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).instances.append(self)
        self.init_kwargs = kwargs
        self.started = 0
        self.closed = 0
        self.fetches: list[str] = []
        self._responses: list[FakePage | Exception] = []

    def script(self, responses: list[FakePage | Exception]) -> None:
        self._responses = list(responses)

    async def start(self) -> None:
        self.started += 1

    async def close(self) -> None:
        self.closed += 1

    async def fetch(self, url: str, **_kwargs: object) -> FakePage:
        self.fetches.append(url)
        if not self._responses:
            return FakePage(status=200, html_content="<html>real record</html>", url=url)
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@pytest.fixture
def fast_config() -> GatewayConfig:
    """Config that makes tests near-instant (no real backoff sleeps)."""
    return GatewayConfig(
        user_agent="bibliohack-test/0.1",
        rate_per_second=1000.0,  # effectively unthrottled
        burst=1000,
        jitter_seconds=0.0,
        fetch_timeout_seconds=1.0,
        max_retries=2,
        backoff_base_seconds=0.0,  # zero-time backoff for tests
        backoff_cap_seconds=0.0,
    )


@pytest.fixture
def install_fake_fetcher(monkeypatch: pytest.MonkeyPatch):
    """Replace the lazy `StealthyFetcher` import inside the gateway module.

    Patching `sys.modules["scrapling.fetchers"]` means the `from scrapling.fetchers
    import StealthyFetcher` inside `fetch_record` resolves to whatever fake
    class we supply.
    """
    import sys
    import types

    def _install(
        fetcher: FakeFetcher | None = None,
        *,
        session_cls: type | None = None,
    ) -> None:
        module = types.ModuleType("scrapling.fetchers")
        if fetcher is not None:
            module.StealthyFetcher = fetcher  # type: ignore[attr-defined]
        if session_cls is not None:
            module.AsyncStealthySession = session_cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "scrapling", types.ModuleType("scrapling"))
        monkeypatch.setitem(sys.modules, "scrapling.fetchers", module)

    return _install


# ───────────────────────────────────────────────────────────────
# Happy path
# ───────────────────────────────────────────────────────────────


async def test_ok_response_returns_ok_outcome(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    fake = FakeFetcher([FakePage(status=200, html_content="<html>real record</html>")])
    install_fake_fetcher(fake)

    gateway = ScraplingOpacGateway(fast_config)
    result = await gateway.fetch_record(Titn(1))

    assert result.outcome is FetchOutcome.OK
    assert result.status_code == 200
    assert result.html == "<html>real record</html>"
    assert result.bytes_in > 0
    assert result.latency_ms >= 0
    assert "TITN=1" in result.url
    assert fake.calls == [result.url]


# ───────────────────────────────────────────────────────────────
# Not found
# ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "marker_html",
    [
        # The "real" not-found markers verified against the live OPAC for an
        # invented TITN (99999999) in May 2026:
        "<p>Esta consulta NO recupera resultados</p>",
        "<span>Para una búsqueda en cualquier campo (0 docs.)</span>",
        # Defensive matches in case the upstream wording drifts back:
        "<p>No se ha encontrado el registro</p>",
        "Registro no encontrado",
    ],
)
async def test_not_found_marker_yields_not_found_outcome(
    marker_html: str,
    fast_config: GatewayConfig,
    install_fake_fetcher,
) -> None:
    fake = FakeFetcher([FakePage(status=200, html_content=marker_html)])
    install_fake_fetcher(fake)

    result = await ScraplingOpacGateway(fast_config).fetch_record(Titn(999_999))
    assert result.outcome is FetchOutcome.NOT_FOUND
    assert result.status_code == 200


# ───────────────────────────────────────────────────────────────
# Permanent errors (4xx other than the not-found marker)
# ───────────────────────────────────────────────────────────────


async def test_4xx_returns_permanent_error(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    fake = FakeFetcher([FakePage(status=403, html_content="forbidden")])
    install_fake_fetcher(fake)

    result = await ScraplingOpacGateway(fast_config).fetch_record(Titn(1))
    assert result.outcome is FetchOutcome.PERMANENT_ERROR
    assert result.status_code == 403
    assert result.error is not None
    assert "403" in result.error


# ───────────────────────────────────────────────────────────────
# Transient errors → retry → eventually OK
# ───────────────────────────────────────────────────────────────


async def test_5xx_then_200_eventually_succeeds(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    fake = FakeFetcher(
        [
            FakePage(status=503, html_content="upstream busy"),
            FakePage(status=200, html_content="<html>real record</html>"),
        ]
    )
    install_fake_fetcher(fake)

    result = await ScraplingOpacGateway(fast_config).fetch_record(Titn(1))
    assert result.outcome is FetchOutcome.OK
    assert len(fake.calls) == 2


async def test_retries_exhausted_raises_unavailable(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    # max_retries=2 → 3 total attempts allowed; supply 4 failures so we exhaust.
    fake = FakeFetcher([FakePage(status=503, html_content="busy")] * 4)
    install_fake_fetcher(fake)

    with pytest.raises(OpacUnavailableError, match="OPAC unavailable"):
        await ScraplingOpacGateway(fast_config).fetch_record(Titn(1))
    # We made max_retries+1 attempts before giving up.
    assert len(fake.calls) == fast_config.max_retries + 1


async def test_exception_during_fetch_is_retried(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    err = TimeoutError("simulated timeout")
    fake = FakeFetcher([err, FakePage(status=200, html_content="<html>ok</html>")])
    install_fake_fetcher(fake)

    result = await ScraplingOpacGateway(fast_config).fetch_record(Titn(1))
    assert result.outcome is FetchOutcome.OK
    assert len(fake.calls) == 2


async def test_repeated_exceptions_raise_unavailable(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    fake = FakeFetcher(
        [
            ConnectionError("net down"),
            ConnectionError("net down"),
            ConnectionError("net down"),
            ConnectionError("net down"),
        ]
    )
    install_fake_fetcher(fake)

    with pytest.raises(OpacUnavailableError):
        await ScraplingOpacGateway(fast_config).fetch_record(Titn(1))


# ───────────────────────────────────────────────────────────────
# Charset repair — AbsysNET declares iso-8859-1 but serves UTF-8, so
# Chromium hands us mojibake. The gateway must undo it before returning.
# ───────────────────────────────────────────────────────────────


def _mojibake(text: str) -> str:
    """Reproduce the bug: UTF-8 bytes decoded as Latin-1 (what Chromium does)."""
    return text.encode("utf-8").decode("latin-1")


def test_repair_charset_undoes_latin1_misread_of_utf8() -> None:
    from bibliohack.catalog.infrastructure.absysnet.gateway import _repair_charset

    original = "091 / Juan Jesús García, Juan Enrique Gómez."
    page = (
        '<html><head><meta charset="iso-8859-1"></head>'
        f"<body><span>{_mojibake(original)}</span></body></html>"
    )
    repaired = _repair_charset(page)
    assert original in repaired
    assert "Ã" not in repaired


def test_repair_charset_left_alone_when_no_latin1_declaration() -> None:
    """A correctly-served UTF-8 page (no Latin-1 declaration) is untouched."""
    from bibliohack.catalog.infrastructure.absysnet.gateway import _repair_charset

    page = '<html><head><meta charset="utf-8"></head><body><span>Gómez</span></body></html>'
    assert _repair_charset(page) == page


def test_repair_charset_recovers_fields_despite_stray_invalid_byte() -> None:
    """A stray non-UTF-8 byte elsewhere must not block repairing the content.

    Real OPAC pages are UTF-8 mis-decoded as Latin-1, but carry the odd
    invalid byte inside inline scripts. A strict whole-doc decode would throw
    and silently leave mojibake; the lenient fallback still recovers the
    bibliographic text and only replaces the genuinely-invalid byte.
    """
    from bibliohack.catalog.infrastructure.absysnet.gateway import _repair_charset

    original = "Jesús García"
    page = (
        '<html><head><meta charset="iso-8859-1"></head>'
        f"<body><span>{_mojibake(original)}</span>"
        "<script>var x='\x9d';</script></body></html>"  # 0x9d: invalid UTF-8
    )
    repaired = _repair_charset(page)
    assert original in repaired  # content recovered
    assert "Ã" not in repaired


def test_repair_charset_skips_pages_without_latin1_declaration() -> None:
    """No Latin-1 declaration → never touched (guards correctly-served pages)."""
    from bibliohack.catalog.infrastructure.absysnet.gateway import _repair_charset

    page = "<html><body>caf\xe9</body></html>"  # no charset meta at all
    assert _repair_charset(page) == page


async def test_fetch_record_returns_repaired_html(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    original = "García, Juan Jesús."
    html = (
        '<html><head><meta charset="iso-8859-1"></head>'
        f"<body><span>{_mojibake(original)}</span></body></html>"
    )
    fake = FakeFetcher([FakePage(status=200, html_content=html)])
    install_fake_fetcher(fake)

    result = await ScraplingOpacGateway(fast_config).fetch_record(Titn(1))

    assert result.outcome is FetchOutcome.OK
    assert original in result.html
    assert "Ã" not in result.html


# ───────────────────────────────────────────────────────────────
# Pooled browser session — one Camoufox launch per run, reused for every
# fetch (the throughput win), torn down on exit. Politeness is unchanged:
# the session is single-page (max_pages=1) and the throttle still gates each
# request; this only stops paying the launch cost per record.
# ───────────────────────────────────────────────────────────────


async def test_pooled_session_opened_once_reused_and_closed(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    FakeAsyncSession.instances.clear()
    fake = FakeFetcher([])  # must NOT be touched while a session is open
    install_fake_fetcher(fake, session_cls=FakeAsyncSession)

    gateway = ScraplingOpacGateway(fast_config)
    async with gateway:
        await gateway.fetch_record(Titn(1))
        await gateway.fetch_record(Titn(2))

    # Exactly one browser session for the whole run.
    assert len(FakeAsyncSession.instances) == 1
    session = FakeAsyncSession.instances[0]
    assert session.started == 1
    assert session.closed == 1
    # Both fetches were routed through the pooled session, not the one-shot
    # StealthyFetcher (which would launch a browser per call).
    assert len(session.fetches) == 2
    assert fake.calls == []
    # Single-page session ⇒ strictly serial ⇒ politeness preserved.
    assert session.init_kwargs.get("max_pages") == 1


async def test_open_session_is_idempotent(fast_config: GatewayConfig, install_fake_fetcher) -> None:
    FakeAsyncSession.instances.clear()
    install_fake_fetcher(session_cls=FakeAsyncSession)

    gateway = ScraplingOpacGateway(fast_config)
    await gateway.open_session()
    await gateway.open_session()  # no-op — must not spawn a second browser
    try:
        assert len(FakeAsyncSession.instances) == 1
        assert FakeAsyncSession.instances[0].started == 1
    finally:
        await gateway.close_session()
    assert FakeAsyncSession.instances[0].closed == 1


async def test_without_session_falls_back_to_oneshot_fetcher(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    FakeAsyncSession.instances.clear()
    fake = FakeFetcher([FakePage(status=200, html_content="<html>real record</html>")])
    install_fake_fetcher(fake, session_cls=FakeAsyncSession)

    # No `async with` → no pooled session → one-shot StealthyFetcher per call.
    result = await ScraplingOpacGateway(fast_config).fetch_record(Titn(1))

    assert result.outcome is FetchOutcome.OK
    assert len(fake.calls) == 1
    assert FakeAsyncSession.instances == []


async def test_close_session_without_open_is_noop(
    fast_config: GatewayConfig,
) -> None:
    # Closing a gateway that never opened a session must not raise.
    await ScraplingOpacGateway(fast_config).close_session()


# ───────────────────────────────────────────────────────────────
# Hard fetch timeout + session recycling — regression tests for the
# 2026-07-03 / 2026-07-08 crawl-plane hangs: after a Page.goto timeout the
# pooled session's page slot wedged and the NEXT fetch never returned,
# freezing the job (and everything behind the crawl flock) for days.
# ───────────────────────────────────────────────────────────────


class WedgedSession(FakeAsyncSession):
    """First session instance hangs forever on fetch (a wedged driver);
    any later instance answers normally."""

    instances: ClassVar[list[FakeAsyncSession]] = []

    async def fetch(self, url: str, **_kwargs: object) -> FakePage:
        self.fetches.append(url)
        if self is type(self).instances[0]:
            await asyncio.sleep(3600)  # never returns within any test budget
        return FakePage(status=200, html_content="<html>real record</html>", url=url)


class FailingOnceSession(FakeAsyncSession):
    """First session instance raises on fetch; any later instance is fine."""

    instances: ClassVar[list[FakeAsyncSession]] = []

    async def fetch(self, url: str, **_kwargs: object) -> FakePage:
        self.fetches.append(url)
        if self is type(self).instances[0]:
            msg = "simulated render failure"
            raise ConnectionError(msg)
        return FakePage(status=200, html_content="<html>real record</html>", url=url)


async def test_wedged_fetch_hits_hard_timeout_and_retries_on_fresh_session(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    WedgedSession.instances.clear()
    install_fake_fetcher(session_cls=WedgedSession)
    config = replace(fast_config, fetch_hard_timeout_seconds=0.05)

    gateway = ScraplingOpacGateway(config)
    async with gateway:
        result = await gateway.fetch_record(Titn(1))

    # The hang was bounded by the hard timeout (not Playwright's), the wedged
    # session was recycled, and the retry succeeded on a fresh browser.
    assert result.outcome is FetchOutcome.OK
    assert len(WedgedSession.instances) == 2
    assert WedgedSession.instances[0].closed == 1
    assert WedgedSession.instances[1].fetches  # retry ran on the new session


async def test_render_error_recycles_pooled_session_before_retry(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    FailingOnceSession.instances.clear()
    install_fake_fetcher(session_cls=FailingOnceSession)

    gateway = ScraplingOpacGateway(fast_config)
    async with gateway:
        result = await gateway.fetch_record(Titn(1))

    # An ordinary render exception must not reuse the possibly-wedged page
    # slot: the session is replaced and the retry uses the fresh one.
    assert result.outcome is FetchOutcome.OK
    assert len(FailingOnceSession.instances) == 2
    assert FailingOnceSession.instances[0].closed == 1


# ───────────────────────────────────────────────────────────────
# HTTP-first record fetch — plain httpx before the Camoufox render.
# Wire shape (verified live 2026-07-02): the canonical `?TITN=N` URL serves a
# meta-refresh page pointing at `/abnetcl.cgi/{TOKEN}?ACC=161`; that URL
# serves the record view; the token can then be reused as
# `/abnetcl.cgi/{TOKEN}?TITN=M` — one request per record.
# ───────────────────────────────────────────────────────────────

_TOKEN_PATH = "/cultura/absys/abnopac/abnetcl.cgi/FAKETOKEN123"
_REFRESH_PAGE = (
    '<html><head><meta charset="iso-8859-1">'
    f'<meta http-equiv="Refresh" content="0; URL={_TOKEN_PATH}?ACC=161" />'
    "</head></html>"
)


def _record_page(titn: int) -> str:
    return f'<html><body><span class="js-TITN">{titn}</span></body></html>'


_NOT_FOUND_PAGE = "<html><body><p>Esta consulta NO recupera resultados (0 docs.)</p></body></html>"


class HttpScript:
    """Scripted httpx.MockTransport handler that records every request URL."""

    def __init__(self, *, not_found: bool = False) -> None:
        self.calls: list[str] = []
        self.expired_tokens: tuple[str, ...] = ()
        self._not_found = not_found

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        titn = request.url.params.get("TITN")
        if request.url.path.endswith("FAKETOKEN123") and titn is not None:
            # Token-reuse fetch.
            if url in self.expired_tokens:
                return httpx.Response(200, text=_REFRESH_PAGE)
            if self._not_found:
                return httpx.Response(200, text=_NOT_FOUND_PAGE)
            return httpx.Response(200, text=_record_page(int(titn)))
        if request.url.path.endswith("FAKETOKEN123"):
            # ACC=161 render after the meta-refresh hop; the TITN being viewed
            # is the one from the immediately-preceding canonical request.
            if self._not_found:
                return httpx.Response(200, text=_NOT_FOUND_PAGE)
            return httpx.Response(200, text=_record_page(int(self.calls[-2].split("TITN=")[1])))
        # Canonical ?TITN=N bootstrap URL → meta-refresh page.
        return httpx.Response(200, text=_REFRESH_PAGE)


def _http_first_gateway(fast_config: GatewayConfig, handler) -> ScraplingOpacGateway:
    return ScraplingOpacGateway(
        replace(fast_config, http_first=True),
        http_transport=httpx.MockTransport(handler),
    )


async def test_http_first_bootstraps_then_reuses_token(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    # A FakeFetcher with no scripted responses raises if the browser path is
    # ever touched — the sentinel that HTTP handled everything.
    install_fake_fetcher(FakeFetcher([]))
    handler = HttpScript()
    gateway = _http_first_gateway(fast_config, handler)

    first = await gateway.fetch_record(Titn(68990))
    second = await gateway.fetch_record(Titn(68998))

    assert first.outcome is FetchOutcome.OK
    assert 'class="js-TITN">68990' in first.html
    assert second.outcome is FetchOutcome.OK
    assert 'class="js-TITN">68998' in second.html
    # Bootstrap = 2 requests (canonical + refresh); reuse = 1 request.
    assert len(handler.calls) == 3
    assert handler.calls[2].endswith("FAKETOKEN123?TITN=68998")


async def test_http_first_not_found_detected_without_browser(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    install_fake_fetcher(FakeFetcher([]))
    gateway = _http_first_gateway(fast_config, HttpScript(not_found=True))

    result = await gateway.fetch_record(Titn(50000))
    assert result.outcome is FetchOutcome.NOT_FOUND


async def test_http_first_expired_token_rebootstraps(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    install_fake_fetcher(FakeFetcher([]))
    handler = HttpScript()
    gateway = _http_first_gateway(fast_config, handler)
    await gateway.fetch_record(Titn(1))  # mints the token (2 requests)

    # Expire the token for the next reuse URL only.
    handler.expired_tokens = (f"https://www.juntadeandalucia.es{_TOKEN_PATH}?TITN=2",)
    result = await gateway.fetch_record(Titn(2))

    assert result.outcome is FetchOutcome.OK
    # reuse-miss (1) + fresh bootstrap (2) on top of the initial 2.
    assert len(handler.calls) == 5


async def test_http_first_unknown_shape_falls_back_to_browser(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    class WeirdPages:
        calls: ClassVar[list[str]] = []

        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.calls.append(str(request.url))
            return httpx.Response(200, text="<html>maintenance page</html>")

    fake = FakeFetcher([FakePage(status=200, html_content="<html>real record</html>")])
    install_fake_fetcher(fake)
    gateway = _http_first_gateway(fast_config, WeirdPages())

    result = await gateway.fetch_record(Titn(7))

    assert result.outcome is FetchOutcome.OK
    assert result.html == "<html>real record</html>"
    assert len(fake.calls) == 1  # browser fallback used


async def test_http_first_transport_error_falls_back_to_browser(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        msg = "simulated network failure"
        raise httpx.ConnectError(msg, request=request)

    fake = FakeFetcher([FakePage(status=200, html_content="<html>real record</html>")])
    install_fake_fetcher(fake)
    gateway = _http_first_gateway(fast_config, boom)

    result = await gateway.fetch_record(Titn(7))
    assert result.outcome is FetchOutcome.OK
    assert len(fake.calls) == 1


async def test_http_first_decodes_utf8_despite_latin1_declaration(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    """Raw UTF-8 bytes must decode correctly — no mojibake, no _repair_charset."""
    original = "Cartografía peninsular / Ignasi M. Colomer"

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            '<html><head><meta charset="iso-8859-1"></head>'
            f'<body><span class="js-TITN">9</span><span>{original}</span></body></html>'
        ).encode()
        return httpx.Response(
            200, content=body, headers={"Content-Type": "text/html; charset=iso-8859-1"}
        )

    install_fake_fetcher(FakeFetcher([]))
    gateway = _http_first_gateway(fast_config, handler)

    result = await gateway.fetch_record(Titn(9))
    assert result.outcome is FetchOutcome.OK
    assert original in result.html
    assert "Ã" not in result.html


async def test_http_first_off_by_default_uses_browser(
    fast_config: GatewayConfig, install_fake_fetcher
) -> None:
    """Direct GatewayConfig construction (tests, probes) keeps browser-only."""
    fake = FakeFetcher([FakePage(status=200, html_content="<html>real record</html>")])
    install_fake_fetcher(fake)

    result = await ScraplingOpacGateway(fast_config).fetch_record(Titn(1))
    assert result.outcome is FetchOutcome.OK
    assert len(fake.calls) == 1
