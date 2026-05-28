"""Base class for domain events.

Domain events are immutable records of something that has happened in the
domain. Aggregates raise them; the application layer dispatches them; other
contexts subscribe.

Keep them small, named in past tense, and never expose mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Immutable record of something that happened in the domain."""

    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
