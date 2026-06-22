"""Ports for the holdings application layer (Libraries milestone).

Protocols the use cases depend on, kept free of SQLAlchemy/httpx so the
application logic stays unit-testable behind fakes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence


class UngeocodedBranch(Protocol):
    """The minimal branch shape the geocode sweep needs.

    Read-only properties (not bare attributes) so a frozen row implementing it is
    a covariant subtype — ``Sequence[ConcreteRow]`` then satisfies
    ``Sequence[UngeocodedBranch]``.
    """

    @property
    def code(self) -> str: ...
    @property
    def municipality(self) -> str | None: ...
    @property
    def province(self) -> str | None: ...


class BranchGeoRepository(Protocol):
    """Read ungeocoded branches and write back resolved coordinates."""

    async def iter_ungeocoded(self, *, limit: int, offset: int = 0) -> Sequence[UngeocodedBranch]:
        """Branches with a municipality but no lat/lng yet (a work queue)."""
        ...

    async def set_geo(self, code: str, *, lat: float, lng: float) -> None:
        """Persist resolved coordinates for one branch."""
        ...


class Geocoder(Protocol):
    """Resolve a municipality (+ optional province) to a lat/lng centroid."""

    async def geocode(
        self, *, municipality: str, province: str | None = None
    ) -> tuple[float, float] | None: ...
