"""Cover — the cover-enrichment aggregate (one row of the `covers` table).

The image *bytes* live in the CoverStore, content-addressed by `sha256`
(§7.5.5); this is the metadata: which ISBN, where it came from, its status,
and the content address. `sha256` is set only when `status` is RESOLVED.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class CoverStatus(StrEnum):
    """Lifecycle of a cover resolution attempt."""

    PENDING = "pending"  # known ISBN, not yet attempted
    RESOLVED = "resolved"  # image stored; sha256 is set
    NOFOUND = "nofound"  # no provider had it → frontend shows a placeholder
    FAILED = "failed"  # a provider/processing error; retried on a slow cadence


class CoverSource(StrEnum):
    """Where a cover came from — tracked for attribution / takedown (§7.5.5)."""

    OPENLIBRARY = "openlibrary"
    GOOGLEBOOKS = "googlebooks"
    ABSYS = "absys"
    PLACEHOLDER = "placeholder"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Cover:
    """Metadata for one resolved (or attempted) cover, keyed by ISBN-13."""

    isbn_13: str
    status: CoverStatus
    source: CoverSource = CoverSource.UNKNOWN
    record_id: UUID | None = None
    license: str | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    fetched_at: datetime | None = None

    @property
    def is_resolved(self) -> bool:
        return self.status is CoverStatus.RESOLVED and self.sha256 is not None
