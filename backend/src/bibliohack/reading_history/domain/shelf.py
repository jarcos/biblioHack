"""Reading-history domain — a user's bookshelf and how it maps to the catalogue.

Each shelf entry belongs to one registered user (the `User` aggregate lives in
the identity context; this context references owners by id only). An entry is
a book the reader logged on Goodreads (or, later, another source), optionally
*matched* to a record in our Andalusian catalogue so we can show its cover and
live availability and feed the recommender.
"""

from __future__ import annotations

from enum import StrEnum


class Shelf(StrEnum):
    """Which shelf an entry sits on — Goodreads' three exclusive shelves.

    `value` matches the Goodreads "Exclusive Shelf" column verbatim so import
    is a direct map; the UI localises the labels (Leído / Leyendo / Pendiente).
    """

    READ = "read"
    CURRENTLY_READING = "currently-reading"
    TO_READ = "to-read"

    @classmethod
    def from_goodreads(cls, raw: str) -> Shelf:
        """Map a Goodreads 'Exclusive Shelf' value, defaulting unknowns to TO_READ."""
        try:
            return cls(raw.strip())
        except ValueError:
            return cls.TO_READ


class MatchVia(StrEnum):
    """How a shelf entry was linked to a catalogue record (provenance of the match).

    Drives both UI badges and re-match policy: NONE/TITLE_AUTHOR entries are
    worth re-checking as the catalogue grows; ISBN matches are authoritative.
    """

    ISBN = "isbn"
    TITLE_AUTHOR = "title_author"
    NONE = "none"
