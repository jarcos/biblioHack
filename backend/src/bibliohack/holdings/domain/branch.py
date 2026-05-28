"""Branch — a library / sub-library / sucursal in the RBPA network.

`BranchCode` is the natural key assigned by AbsysNET (e.g. ``"21001"``).
We keep that string as the primary identifier rather than minting our own
UUID, because the upstream system is the source of truth for branch identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from bibliohack.shared.domain import Entity


@dataclass(frozen=True, slots=True)
class BranchCode:
    """Opaque textual branch code as used by AbsysNET (e.g. ``"21001"``)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            msg = "BranchCode must not be blank"
            raise ValueError(msg)

    def __str__(self) -> str:
        return self.value


class Branch(Entity[BranchCode]):
    """A physical or logical library branch in the network."""

    def __init__(
        self,
        *,
        code: BranchCode,
        name: str,
        municipality: str | None = None,
        province: str | None = None,
        is_active: bool = True,
        first_seen_at: datetime | None = None,
    ) -> None:
        super().__init__(code)
        if not name.strip():
            msg = "Branch name must not be blank"
            raise ValueError(msg)
        self.name = name.strip()
        self.municipality = municipality
        self.province = province
        self.is_active = is_active
        self.first_seen_at = first_seen_at or datetime.now(tz=UTC)

    @property
    def code(self) -> BranchCode:
        return self.id
