"""Tests for ScraplingOpacGateway.

We don't drive Scrapling for real here — that would require Camoufox and a
running OPAC. Instead we monkeypatch the lazy `StealthyFetcher.async_fetch`
import to return fake responses, which lets us exhaustively cover the state
machine (OK / NOT_FOUND / PERMANENT / retry-then-fail).

Integration tests against the live OPAC live in `tests/catalog/integration/`
and are skipped by default.
"""

from __future__ import annotations

from dataclasses import dataclass

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

    def _install(fetcher: FakeFetcher) -> None:
        module = types.ModuleType("scrapling.fetchers")
        module.StealthyFetcher = fetcher  # type: ignore[attr-defined]
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
