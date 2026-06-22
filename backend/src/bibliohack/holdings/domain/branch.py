"""Branch — a library / sub-library / sucursal in the RBPA network.

`BranchCode` is the natural key assigned by AbsysNET (e.g. ``"21001"``).
We keep that string as the primary identifier rather than minting our own
UUID, because the upstream system is the source of truth for branch identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from bibliohack.shared.domain import Entity

# Branch names often carry the library's *dedication* after the town, e.g.
# "Carcabuey-Almudena Grandes", "Nijar. Red de Bibliotecas...",
# "Casabermeja - B.P. Unicaja". The town is the part before the first
# separator (that's what geocodes): a hyphen, an en dash, or ". ".
_TOWN_SEPARATOR = re.compile("\\s*[-–]\\s*|\\.\\s+")  # noqa: RUF001 (en dash is intentional)


def clean_branch_municipality(name: str) -> str:
    """The geocodable town from a (possibly dedication-suffixed) branch name.

    ``"Carcabuey-Almudena Grandes"`` → ``"Carcabuey"``;
    ``"Níjar. Red de Bibliotecas…"`` → ``"Níjar"``;
    a plain ``"Vélez Rubio"`` is returned unchanged.
    """
    return _TOWN_SEPARATOR.split(name, maxsplit=1)[0].strip()


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
        address: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        url: str | None = None,
        phone: str | None = None,
        opening_hours: str | None = None,
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
        self.address = address
        self.lat = lat
        self.lng = lng
        self.url = url
        self.phone = phone
        self.opening_hours = opening_hours
        self.is_active = is_active
        self.first_seen_at = first_seen_at or datetime.now(tz=UTC)

    @property
    def code(self) -> BranchCode:
        return self.id

    @property
    def has_geo(self) -> bool:
        """True once the branch has been geocoded (usable for proximity sort)."""
        return self.lat is not None and self.lng is not None
