"""Canon seed — the "works worth having" list that drives canon import.

The one rule (see ``docs/design/canon-import.md``): biblioHack is a *mirror* of
what the Red de Bibliotecas Públicas de Andalucía actually holds. So external
knowledge bases (Wikidata, award lists, Open Library) are **not** imported as
catalogue records — that would invent holdings with no copies and no
availability. Instead they become a **canon seed**: a curated list of canonical
works that feeds two separate workstreams (acquisition + a positive-only
relevance boost).

This module is the pure heart of phase C0/C1. It knows nothing about SPARQL,
HTTP, or SQL: it defines the seed value object, the small enums the schema
stores, and the helpers that normalise a raw external work into a clean,
match-ready :class:`CanonSeedWork`. The Wikidata HTTP client and the Postgres
repository depend on these types, not the other way round, so the normalisation
rules (ISBN cleanup, dedup, plausible-year clamp) stay unit-testable without a
network or a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from bibliohack.catalog.domain.isbn import normalize_to_isbn13
from bibliohack.catalog.domain.pub_year import max_plausible_pub_year

# Publication years outside this band are MARC "unknown date" sentinels (0,
# negatives, 9999) — treated as *unknown* (None), mirroring the catalogue's own
# pub_year handling so a seed never carries a bogus year. The upper bound is the
# shared current-year-plus-buffer ceiling (see catalog.domain.pub_year), not a
# fixed 2100: a seed dated 2029/2033 is a source-data error and must not be stored.
_MIN_PLAUSIBLE_PUB_YEAR = 1


class CanonSource(StrEnum):
    """Where a seed work came from. Stored verbatim in ``canon_seed.source``."""

    WIKIDATA = "wikidata"
    AWARD_LIST = "award_list"
    OPENLIBRARY = "openlibrary"


class AcquireStatus(StrEnum):
    """Lifecycle of a seed work w.r.t. the live OPAC (the C3 acquisition path).

    A fresh seed is ``unchecked``; the C1 matcher does not change this (a match
    against the mirror is recorded via ``matched_record_id``, not here). C3 sets
    ``held`` / ``not_held`` after asking the OPAC, then ``ingested`` once the
    scrape pipeline has pulled the genuinely-held record in.
    """

    UNCHECKED = "unchecked"
    HELD = "held"
    NOT_HELD = "not_held"
    INGESTED = "ingested"


class CanonMatchVia(StrEnum):
    """How a seed work was linked to a mirror record (C1). ``NONE`` = unmatched."""

    ISBN = "isbn"
    TITLE_AUTHOR = "title_author"
    NONE = "none"


def _plausible_year(year: int | None, *, max_year: int | None = None) -> int | None:
    if max_year is None:
        max_year = max_plausible_pub_year()
    if year is None or not (_MIN_PLAUSIBLE_PUB_YEAR <= year <= max_year):
        return None
    return year


def _clean_isbn13s(raw: object) -> tuple[str, ...]:
    """Normalise an iterable of dirty ISBN strings to deduped ISBN-13 keys.

    Routes every value through :func:`normalize_to_isbn13` — the single source
    of truth for the 13-digit key used across the system (the ``isbns`` table
    and the Goodreads matcher both use it), so canon matching can't silently
    miss an ISBN-10-sourced edition. Order is preserved (first occurrence wins)
    so the seed is deterministic across refreshes.
    """
    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw, (list, tuple, set)):
        return ()
    for value in raw:
        if not isinstance(value, str):
            continue
        key = normalize_to_isbn13(value)
        if key is not None and key not in seen:
            seen.add(key)
            out.append(key)
    return tuple(out)


def _clean_awards(raw: object) -> tuple[str, ...]:
    """Trim, drop blanks, and dedup award labels (case-insensitive), order-stable."""
    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw, (list, tuple, set)):
        return ()
    for value in raw:
        if not isinstance(value, str):
            continue
        label = value.strip()
        folded = label.casefold()
        if label and folded not in seen:
            seen.add(folded)
            out.append(label)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class CanonSeedWork:
    """One canonical work in the seed, normalised and ready to match/upsert.

    Identity is ``(source, source_ref)`` — e.g. ``("wikidata", "Q12345")`` — so
    a refresh upserts in place (idempotent). ``isbn13`` / ``awards`` are cleaned
    and deduped on construction; ``pub_year`` is clamped to a plausible year or
    ``None``; ``notability`` is a non-negative ranking hint (Wikipedia sitelink
    count for Wikidata works).
    """

    source: CanonSource
    source_ref: str
    title: str
    author: str | None = None
    pub_year: int | None = None
    isbn13: tuple[str, ...] = field(default_factory=tuple)
    awards: tuple[str, ...] = field(default_factory=tuple)
    notability: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ref", self.source_ref.strip())
        object.__setattr__(self, "title", self.title.strip())
        author = self.author.strip() if self.author else None
        object.__setattr__(self, "author", author or None)
        object.__setattr__(self, "pub_year", _plausible_year(self.pub_year))
        object.__setattr__(self, "isbn13", _clean_isbn13s(self.isbn13))
        object.__setattr__(self, "awards", _clean_awards(self.awards))
        object.__setattr__(self, "notability", max(0, int(self.notability)))
        if not self.source_ref:
            msg = "CanonSeedWork.source_ref must be non-empty"
            raise ValueError(msg)
        if not self.title:
            msg = "CanonSeedWork.title must be non-empty"
            raise ValueError(msg)
