"""Base class marker for value objects.

Value objects are equal by *value*: two `Isbn` instances with the same digits
are the same Isbn. Implement them as frozen dataclasses (or pydantic models with
`frozen=True`) so equality and hashability come for free.

This module exists for the marker / vocabulary; it intentionally has no
behaviour. Subclasses should be `@dataclass(frozen=True, slots=True)`.
"""

from __future__ import annotations


class ValueObject:
    """Marker base for value objects. Subclasses must be frozen dataclasses."""

    __slots__ = ()
