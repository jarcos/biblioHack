"""Schemathesis contract tests over the identity-milestone surface.

Property-based fuzzing of /api/auth/*, /api/account* and /api/shelf* straight
from the OpenAPI schema: no generated input may ever produce a 5xx. The app
runs with the same in-memory fakes as the unit HTTP suites (no DB, no Redis),
so every covered endpoint either handles the input or rejects it cleanly —
endpoints that would hit the real database (catalog search) are excluded.

Auth-gated endpoints respond 401 before touching any repository, which is
exactly the contract we want fuzzed: unauthenticated garbage must never
reach a handler body.
"""

from __future__ import annotations

import gc
import warnings
from typing import TYPE_CHECKING

import pytest
import schemathesis
from hypothesis import settings
from schemathesis.checks import not_a_server_error

from bibliohack.identity.interfaces.http.dependencies import (
    get_captcha_verifier,
    get_mailer,
    get_password_hasher,
    get_session_store,
    get_token_service,
    get_user_repository,
)
from bibliohack.interfaces.http.app import create_app
from bibliohack.interfaces.http.dependencies import get_rate_limiter
from tests.identity.fakes import (
    AlwaysPassCaptcha,
    FakePasswordHasher,
    InMemorySessionStore,
    InMemoryTokenService,
    InMemoryUserRepository,
    RecordingMailer,
)
from tests.shared.fakes import AllowAllRateLimiter

if TYPE_CHECKING:
    from collections.abc import Iterator

# Schemathesis drives each case through httpx's ASGITransport, whose anyio
# memory streams are finalised by GC rather than closed eagerly. Under our
# global `filterwarnings = error` those ResourceWarnings surface as
# PytestUnraisableExceptionWarning failures that have nothing to do with the
# contract under test — so this module opts out of that one warning…
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")


@pytest.fixture(autouse=True)
def _flush_transport_garbage() -> Iterator[None]:
    """…and flushes the stream finalisers *inside* this module's tests.

    Without the explicit collect, the lazily-GC'd streams would surface in
    whichever test (in any module) happens to run when GC fires — the same
    flaky-attribution failure mode the isolation suite fixed for asyncpg.
    """
    yield
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        gc.collect()


def _app():
    app = create_app()
    app.dependency_overrides[get_user_repository] = InMemoryUserRepository
    app.dependency_overrides[get_session_store] = InMemorySessionStore
    app.dependency_overrides[get_token_service] = InMemoryTokenService
    app.dependency_overrides[get_mailer] = RecordingMailer
    app.dependency_overrides[get_password_hasher] = FakePasswordHasher
    app.dependency_overrides[get_captcha_verifier] = AlwaysPassCaptcha
    app.dependency_overrides[get_rate_limiter] = AllowAllRateLimiter
    return app


schema = schemathesis.openapi.from_asgi("/openapi.json", _app()).include(
    path_regex=r"^/api/(auth|account|shelf)"
)


@schema.parametrize()
@settings(max_examples=25, deadline=None)
def test_no_input_produces_a_server_error(case: schemathesis.Case) -> None:
    case.call_and_validate(checks=(not_a_server_error,))
