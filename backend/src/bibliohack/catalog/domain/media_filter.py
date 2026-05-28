"""Media-type filter — which records the worker chooses to persist.

The OPAC catalogues much more than books: magazines (`LDR/07=s`),
audiobooks (`LDR/06=i`), CDs (`LDR/06=j`), DVDs (`LDR/06=g`), sheet music,
electronic resources, etc. For M1's "books-only" requirement we filter
based on the two MARC leader positions the parser already extracts:

    LDR/06 — record type:
        a  language material (printed text)
        c  notated music (sheet music)
        d  manuscript notated music
        e  cartographic material (maps)
        f  manuscript cartographic
        g  projected medium (film, video)
        i  nonmusical sound recording (audiobook)
        j  musical sound recording (CD, vinyl)
        k  two-dimensional nonprojectable graphic (poster)
        m  computer file (software)
        o  kit
        p  mixed materials
        r  three-dimensional artifact
        t  manuscript language material

    LDR/07 — bibliographic level:
        a  monographic component part
        b  serial component part
        c  collection
        d  subunit
        i  integrating resource
        m  monograph / item
        s  serial (magazine, journal, newspaper)

A "printed or electronic book" is the canonical (a, m) intersection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MediaTypeFilterPreset(StrEnum):
    """Named policies for `--filter` on the CLI. Stable across releases."""

    BOOK = "book"
    BOOK_AND_AUDIO = "book+audio"
    MONOGRAPH = "monograph"
    ALL = "all"


# Each preset maps to a set of (LDR/06, LDR/07) tuples to keep.
# `None` in either position means "any value".
_PRESETS: dict[MediaTypeFilterPreset, frozenset[tuple[str | None, str | None]]] = {
    MediaTypeFilterPreset.BOOK: frozenset({("a", "m")}),
    MediaTypeFilterPreset.BOOK_AND_AUDIO: frozenset({("a", "m"), ("i", "m")}),
    MediaTypeFilterPreset.MONOGRAPH: frozenset({(None, "m")}),
    MediaTypeFilterPreset.ALL: frozenset({(None, None)}),
}


@dataclass(frozen=True, slots=True)
class MediaTypeFilter:
    """Decide whether a parsed record qualifies for persistence.

    Construct from one of the named presets (the CLI does this) or by
    hand-rolling an `allowed` set when a more exotic policy is needed.
    """

    allowed: frozenset[tuple[str | None, str | None]]

    @classmethod
    def from_preset(cls, preset: MediaTypeFilterPreset) -> MediaTypeFilter:
        return cls(allowed=_PRESETS[preset])

    def accepts(self, ld06: str | None, ld07: str | None) -> bool:
        """Return True if (ld06, ld07) matches one of the allowed combinations.

        Either field being `None` in an allowed entry means 'any value'.
        A record with missing LDR fields (None) only matches an entry that
        explicitly allows None in that slot — i.e. the ALL preset, or a
        partial wildcard like (None, "m").
        """
        for allowed_ld06, allowed_ld07 in self.allowed:
            ld06_ok = allowed_ld06 is None or allowed_ld06 == ld06
            ld07_ok = allowed_ld07 is None or allowed_ld07 == ld07
            if ld06_ok and ld07_ok:
                return True
        return False

    @property
    def is_open(self) -> bool:
        """True if the filter accepts everything (the ALL preset)."""
        return (None, None) in self.allowed
