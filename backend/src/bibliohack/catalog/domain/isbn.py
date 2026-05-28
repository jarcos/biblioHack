"""ISBN — value object with light validation.

We don't depend on `isbnlib` because (a) it's a heavy dep, (b) AbsysNET's ISBN
field is dirty in the wild (hyphens, dashes, embedded commentary) and we want
to keep ingest tolerant. Validation here is intentionally minimal: strip
non-digits, check length is 10 or 13, allow trailing 'X' on ISBN-10. Full
check-digit verification would reject too many real records.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Isbn:
    """ISBN-10 or ISBN-13, normalised to digits-only (uppercase X allowed)."""

    value: str

    def __post_init__(self) -> None:
        normalised = _strip(self.value)
        if not _looks_like_isbn(normalised):
            msg = f"Not a recognisable ISBN: {self.value!r}"
            raise ValueError(msg)
        # Replace the value in-place by going through object.__setattr__
        # (frozen=True prevents normal assignment).
        object.__setattr__(self, "value", normalised)

    @property
    def is_isbn13(self) -> bool:
        return len(self.value) == 13

    @property
    def is_isbn10(self) -> bool:
        return len(self.value) == 10

    def __str__(self) -> str:
        return self.value


def _strip(raw: str) -> str:
    """Remove hyphens, spaces, and the 'ISBN' prefix; uppercase the trailing X."""
    out = raw.strip().upper()
    if out.startswith("ISBN"):
        out = out[4:].lstrip(":").strip()
    return "".join(ch for ch in out if ch.isdigit() or ch == "X")


def _looks_like_isbn(s: str) -> bool:
    if len(s) == 13:
        return s.isdigit()
    if len(s) == 10:
        # ISBN-10 last digit may be 'X' (representing 10 in the check digit)
        return s[:-1].isdigit() and (s[-1].isdigit() or s[-1] == "X")
    return False
