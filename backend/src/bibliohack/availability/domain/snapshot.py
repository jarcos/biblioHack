"""AvailabilitySnapshot — one observation of a copy's loan status at a point in time.

Snapshots are append-only. We never UPDATE one; a status change is a new
row. The table is a TimescaleDB hypertable partitioned on ``observed_at``
so we can keep many years of history cheaply.

The value object intentionally exposes only what is needed by the rest of
the app: an opaque ``copy_id`` (UUID of the local ejemplar row), the
:class:`AvailabilityStatus` enum, a wall-clock timestamp, and an
optional ``due_back_at`` date for loaned items. The raw OPAC string is
kept on the persistence model for drift auditing but is not exposed
through the domain VO — domain code should reason about the enum, not
the wire format.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

    from bibliohack.availability.domain.status import AvailabilityStatus


@dataclass(frozen=True, slots=True)
class AvailabilitySnapshot:
    """One observation of a single copy's status."""

    copy_id: UUID
    observed_at: datetime
    status: AvailabilityStatus
    due_back_at: date | None = None
