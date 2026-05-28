"""Copy — a physical (or virtual) instance of a bibliographic record.

A `Copy` belongs to exactly one `Branch` and references exactly one
`BibliographicRecord` (via its id, *not* a Python reference — copies and
records are in different bounded contexts).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bibliohack.shared.domain import Entity, Identifier

if TYPE_CHECKING:
    from bibliohack.catalog.domain import BibliographicRecordId
    from bibliohack.holdings.domain.branch import BranchCode


@dataclass(frozen=True, slots=True)
class CopyId(Identifier):
    """Internal UUID identifier for a Copy."""


class Copy(Entity[CopyId]):
    """A single physical or virtual exemplar of a bibliographic record."""

    def __init__(
        self,
        *,
        entity_id: CopyId,
        record_id: BibliographicRecordId,
        branch_code: BranchCode,
        signature: str | None = None,
        barcode: str | None = None,
        is_active: bool = True,
        first_seen_at: datetime | None = None,
        last_seen_at: datetime | None = None,
    ) -> None:
        super().__init__(entity_id)
        now = datetime.now(tz=UTC)
        self.record_id = record_id
        self.branch_code = branch_code
        self.signature = signature.strip() if signature else None
        self.barcode = barcode.strip() if barcode else None
        self.is_active = is_active
        self.first_seen_at = first_seen_at or now
        self.last_seen_at = last_seen_at or now

    def touch(self) -> None:
        """Re-observed during a refresh — keep `first_seen_at`, bump `last_seen_at`."""
        self.last_seen_at = datetime.now(tz=UTC)

    def mark_inactive(self) -> None:
        """Copy has been withdrawn / not seen on a fresh scrape."""
        self.is_active = False
        self.last_seen_at = datetime.now(tz=UTC)
