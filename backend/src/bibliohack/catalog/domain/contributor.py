"""Contributor — a person/entity credited on a bibliographic record."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ContributorRole(StrEnum):
    """Role a contributor plays on a record.

    Aligned (loosely) with MARC 21 relator codes. We keep the set small for
    now; expand as the parser encounters new roles. `OTHER` is the catch-all
    so we never lose data even when the role is unrecognised.
    """

    AUTHOR = "author"
    EDITOR = "editor"
    TRANSLATOR = "translator"
    ILLUSTRATOR = "illustrator"
    NARRATOR = "narrator"
    COMPILER = "compiler"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Contributor:
    """A named contribution to a record.

    Value object: identity-by-value. Two contributors with the same (name,
    role) are the same contributor in the context of a record. Deduplication
    across records (linking "García Márquez, Gabriel" everywhere he appears)
    happens later in M3 with authority records.
    """

    name: str
    role: ContributorRole = ContributorRole.AUTHOR

    def __post_init__(self) -> None:
        if not self.name.strip():
            msg = "Contributor name must not be blank"
            raise ValueError(msg)
        # Normalise — collapse internal whitespace, strip ends
        clean = " ".join(self.name.split())
        if clean != self.name:
            object.__setattr__(self, "name", clean)
