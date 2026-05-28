"""Result type for explicit success/failure flow in use cases.

We avoid exception-driven control flow in the application layer. Domain
invariants raise (those are bugs by definition), but expected business outcomes
(NotFound, AlreadyExists, etc.) are returned as `Err`.

Usage:

    def get_record(id: BibliographicRecordId) -> Result[BibliographicRecord, str]:
        rec = repo.find(id)
        if rec is None:
            return Err("record not found")
        return Ok(rec)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ok[T]:
    """Successful result wrapping a value."""

    value: T


@dataclass(frozen=True, slots=True)
class Err[E]:
    """Failed result wrapping an error."""

    error: E


type Result[T, E] = Ok[T] | Err[E]
