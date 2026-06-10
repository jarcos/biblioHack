"""Process-wide Dramatiq broker (Redis, per ARCHITECTURE.md §5.1).

Importing this module configures the broker exactly once. Construction does
NOT connect — Redis is touched only when a message is actually sent or
consumed, so importing actors stays safe in tests and in processes that
never enqueue.
"""

from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from bibliohack.shared.infrastructure.settings import get_settings

_configured = False


def configure_broker() -> None:
    """Idempotently install the Redis broker as Dramatiq's global broker."""
    global _configured  # module-level once-guard
    if _configured:
        return
    # dramatiq ships py.typed but RedisBroker.__init__ itself is unannotated.
    dramatiq.set_broker(RedisBroker(url=get_settings().redis_url))  # type: ignore[no-untyped-call]
    _configured = True
