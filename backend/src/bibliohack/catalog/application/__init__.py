"""catalog — application layer.

Use cases, port interfaces (`OpacGateway`, repositories), DTOs. The domain
doesn't know about these; this layer orchestrates the domain.
"""

from bibliohack.catalog.application.ports import (
    FetchOutcome,
    FetchResult,
    OpacGateway,
    OpacUnavailableError,
    RecordNotFoundError,
    ScraperBudgetExhaustedError,
)

__all__ = [
    "FetchOutcome",
    "FetchResult",
    "OpacGateway",
    "OpacUnavailableError",
    "RecordNotFoundError",
    "ScraperBudgetExhaustedError",
]
