"""Base class for domain entities.

Entities are equal by *identity*, not by value. This is what distinguishes them
from value objects. Two `BibliographicRecord` instances with the same `id` are
the same record even if their state differs (e.g. one is loaded from the DB and
the other has just been mutated in memory).
"""

from __future__ import annotations

from collections.abc import Hashable


class Entity[IdT: Hashable]:
    """Identity-equal domain entity.

    The id type is constrained to `Hashable`, not to `Identifier`, because
    some aggregates use natural keys from upstream systems (e.g. a `Branch`
    keyed by its AbsysNET branch code string) rather than UUIDs. The
    `Identifier` UUID base is a convention to reach for by default; this is
    the escape hatch when the upstream world disagrees.
    """

    def __init__(self, entity_id: IdT) -> None:
        self._id = entity_id

    @property
    def id(self) -> IdT:
        return self._id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return NotImplemented
        return type(self) is type(other) and self._id == other._id

    def __hash__(self) -> int:
        return hash((type(self), self._id))

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self._id}>"
