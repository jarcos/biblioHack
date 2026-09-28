"""Tests for `ScraplingOpacGateway.discover_slice` pagination.

The rendered fetch is replaced with a scripted stub, so these run offline
against small synthetic result pages (plus the real Sep 2026 page fixture).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bibliohack.catalog.infrastructure.absysnet import gateway as gateway_module
from bibliohack.catalog.infrastructure.absysnet.gateway import (
    GatewayConfig,
    ScraplingOpacGateway,
)

FIXTURES = Path(__file__).parent / "fixtures"
CGI = "/cultura/absys/abnopac/abnetcl.cgi/TOKEN"


def _page(titns: list[int], *, total: int, next_doc: int | None) -> str:
    spans = "".join(f'<span class="js-TITN">{t}</span>' for t in titns)
    nxt = (
        f'<a aria-label="Página Siguiente" href="{CGI}/NT1?ACC=161&amp;DOC={next_doc}">&gt;</a>'
        if next_doc is not None
        else ""
    )
    return f"<html><body><p>Búsqueda general ({total} Registros)</p>{spans}{nxt}</body></html>"


class _Scripted:
    """Stands in for `_fetch_rendered`: returns pages in order, records URLs."""

    def __init__(self, pages: list[str]) -> None:
        self._pages = list(pages)
        self.urls: list[str] = []

    async def __call__(self, url: str, *, label: str) -> tuple[int, str, str]:
        del label
        self.urls.append(url)
        return 200, self._pages.pop(0), f"https://opac.test{CGI}?ACC=161"


@pytest.fixture
async def gateway() -> ScraplingOpacGateway:
    # Async so the throttle is built inside the test's running event loop.
    return ScraplingOpacGateway(
        GatewayConfig(
            user_agent="bibliohack-test/0.1",
            rate_per_second=1000.0,
            burst=1000,
            jitter_seconds=0.0,
            fetch_timeout_seconds=1.0,
            max_retries=1,
            backoff_base_seconds=0.0,
            backoff_cap_seconds=0.0,
        )
    )


class _LogSpy:
    """Records warning messages. Spying on the module logger keeps these tests
    independent of global logging config, which other tests reconfigure."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *args: object) -> None:
        self.warnings.append(msg % args)

    def info(self, *_args: object) -> None: ...

    def debug(self, *_args: object) -> None: ...


@pytest.fixture
def log_spy(monkeypatch: pytest.MonkeyPatch) -> _LogSpy:
    spy = _LogSpy()
    monkeypatch.setattr(gateway_module, "log", spy)
    return spy


def _install(
    monkeypatch: pytest.MonkeyPatch, gateway: ScraplingOpacGateway, pages: list[str]
) -> _Scripted:
    stub = _Scripted(pages)
    monkeypatch.setattr(gateway, "_fetch_rendered", stub)
    return stub


async def test_resume_jumps_to_cursor_with_relabelled_control(
    monkeypatch: pytest.MonkeyPatch, gateway: ScraplingOpacGateway
) -> None:
    live_page_1 = (FIXTURES / "search_novedades_2026_09.html").read_text(encoding="utf-8")
    stub = _install(
        monkeypatch,
        gateway,
        [live_page_1, _page([2667207, 2667208], total=63276, next_doc=None)],
    )

    slice_ = await gateway.discover_slice("(@fepu>=2024)", start_offset=56944, max_results=200)

    assert "DOC=56945" in stub.urls[1]
    assert slice_.titns == [2667207, 2667208]
    assert slice_.next_offset == 56946
    assert slice_.total == 63276


async def test_warns_when_results_remain_but_no_next_control(
    monkeypatch: pytest.MonkeyPatch,
    gateway: ScraplingOpacGateway,
    log_spy: _LogSpy,
) -> None:
    # 500 results, 10 on page 1, but no recognisable next-page control: the
    # OPAC's markup changed again. Must not stay silent.
    _install(monkeypatch, gateway, [_page(list(range(1, 11)), total=500, next_doc=None)])

    slice_ = await gateway.discover_slice("(@fepu>=2024)", start_offset=100, max_results=200)

    assert slice_.titns == []
    assert slice_.next_offset == 100
    assert any("absysnet.search.no_next_control" in w for w in log_spy.warnings)


async def test_no_warning_for_a_genuine_single_page_result(
    monkeypatch: pytest.MonkeyPatch,
    gateway: ScraplingOpacGateway,
    log_spy: _LogSpy,
) -> None:
    _install(monkeypatch, gateway, [_page([7, 8, 9], total=3, next_doc=None)])

    slice_ = await gateway.discover_slice("(x.t020.)", start_offset=0, max_results=200)

    assert slice_.titns == [7, 8, 9]
    assert not any("no_next_control" in w for w in log_spy.warnings)


async def test_no_warning_when_cursor_is_caught_up(
    monkeypatch: pytest.MonkeyPatch,
    gateway: ScraplingOpacGateway,
    log_spy: _LogSpy,
) -> None:
    _install(monkeypatch, gateway, [_page(list(range(1, 11)), total=500, next_doc=None)])

    slice_ = await gateway.discover_slice("(@fepu>=2024)", start_offset=500, max_results=200)

    assert slice_.titns == []
    assert not any("no_next_control" in w for w in log_spy.warnings)
