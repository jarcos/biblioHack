"""Ports for the availability bounded context."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable

    from bibliohack.availability.domain.snapshot import AvailabilitySnapshot


class AvailabilitySnapshotRepository(Protocol):
    """Append-only writer for the availability time series.

    Implementations should be idempotent on the (copy_id, observed_at)
    primary key — re-recording the same observation within the same
    timestamp is a no-op, not an error. This matches the M1 scrape
    semantics where re-running the worker for an already-parsed record
    must be safe.
    """

    async def record(self, snapshots: Iterable[AvailabilitySnapshot]) -> int:
        """Append one or more snapshots; return the count actually inserted.

        Existing (copy_id, observed_at) tuples are skipped (ON CONFLICT
        DO NOTHING), so the return value can be smaller than the input.
        """
        ...
