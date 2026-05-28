"""Strongly-typed UUID-based identifier base class.

Subclass per aggregate root so the type system enforces that you never pass a
`BibliographicRecordId` where a `CopyId` is expected. The runtime payload is
always a UUID4; equality is by value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class Identifier:
    """Opaque, value-equal identifier wrapping a UUID."""

    value: UUID

    @classmethod
    def new(cls) -> Self:
        """Generate a fresh identifier."""
        return cls(value=uuid4())

    @classmethod
    def from_string(cls, raw: str) -> Self:
        """Parse from canonical UUID string form."""
        return cls(value=UUID(raw))

    def __str__(self) -> str:
        return str(self.value)
