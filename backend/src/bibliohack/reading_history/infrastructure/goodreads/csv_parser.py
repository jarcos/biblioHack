"""Parse a Goodreads "Export Library" CSV into normalized rows.

Goodreads' export is stable but quirky: ISBN columns are wrapped as Excel
formula literals (`="9788497934329"`) to stop spreadsheets eating leading
zeros, dates are `YYYY/MM/DD`, and a missing rating is `0`. We normalize all of
that here so the matcher/use case sees clean domain values. We deliberately
keep only the fields M4 needs; the rest of the (wide) export is ignored.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from typing import IO

from bibliohack.catalog.domain.isbn import normalize_to_isbn13
from bibliohack.reading_history.domain.shelf import Shelf


@dataclass(frozen=True, slots=True)
class GoodreadsRow:
    """One normalized Goodreads library row (only the fields M4 consumes)."""

    source_book_id: str
    title: str
    author: str | None
    isbn_13: str | None
    shelf: Shelf
    rating: int | None  # 1-5, or None when unrated (Goodreads writes 0)
    review: str | None
    date_read: date | None
    date_added: date | None


def parse_goodreads_csv(stream: IO[str]) -> list[GoodreadsRow]:
    """Read a Goodreads export into `GoodreadsRow`s, skipping rows with no title."""
    rows: list[GoodreadsRow] = []
    for raw in csv.DictReader(stream):
        title = (raw.get("Title") or "").strip()
        book_id = (raw.get("Book Id") or "").strip()
        if not title or not book_id:
            continue
        rows.append(
            GoodreadsRow(
                source_book_id=book_id,
                title=title,
                author=_clean(raw.get("Author")),
                isbn_13=_pick_isbn13(raw),
                shelf=Shelf.from_goodreads(raw.get("Exclusive Shelf") or ""),
                rating=_parse_rating(raw.get("My Rating")),
                review=_clean(raw.get("My Review")),
                date_read=_parse_date(raw.get("Date Read")),
                date_added=_parse_date(raw.get("Date Added")),
            )
        )
    return rows


def _pick_isbn13(raw: dict[str, str]) -> str | None:
    """Best ISBN-13 for the row: prefer ISBN13, fall back to converting ISBN-10.

    Both columns are Excel-escaped (`="..."`); `normalize_to_isbn13` strips any
    non-ISBN characters, so we can hand it the raw cell. Using the same
    normalizer as catalogue ingest guarantees the keys line up.
    """
    for column in ("ISBN13", "ISBN"):
        value = _unescape(raw.get(column))
        if value:
            normalized = normalize_to_isbn13(value)
            if normalized is not None:
                return normalized
    return None


def _unescape(value: str | None) -> str:
    """Strip Goodreads' `="..."` Excel-formula wrapping around ISBN cells."""
    if value is None:
        return ""
    return value.replace("=", "").replace('"', "").strip()


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_rating(value: str | None) -> int | None:
    """Goodreads writes 0 for unrated; map 0 to None, keep 1-5."""
    if value is None:
        return None
    try:
        rating = int(value.strip())
    except ValueError:
        return None
    return rating if 1 <= rating <= 5 else None


def _parse_date(value: str | None) -> date | None:
    """Parse Goodreads' `YYYY/MM/DD`; tolerate blanks and odd formats."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        year, month, day = (int(part) for part in text.split("/"))
        return date(year, month, day)
    except (ValueError, TypeError):
        return None
