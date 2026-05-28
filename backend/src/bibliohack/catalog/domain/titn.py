"""TITN — the AbsysNET sequential permalink identifier.

Lives in the domain because it is the canonical identity of a record at the
source. It is NOT the same as our internal `BibliographicRecordId` (UUID) —
TITN is the *upstream* identifier; UUID is *ours*. Two layers, two purposes,
no mixing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class Titn:
    """Stable upstream identifier assigned by AbsysNET to a bibliographic record.

    Always a positive integer. Construction enforces the invariant — there is
    no `Titn(value=0)` or `Titn(value=-1)` in our system.
    """

    value: int

    def __post_init__(self) -> None:
        if self.value < 1:
            msg = f"TITN must be a positive integer, got {self.value!r}"
            raise ValueError(msg)

    def __str__(self) -> str:
        return str(self.value)

    def __int__(self) -> int:
        return self.value
