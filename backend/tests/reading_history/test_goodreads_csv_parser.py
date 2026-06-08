"""Unit tests for the Goodreads CSV parser — exercises the real export quirks."""

from __future__ import annotations

import io
from datetime import date

from bibliohack.reading_history.domain.shelf import Shelf
from bibliohack.reading_history.infrastructure.goodreads.csv_parser import parse_goodreads_csv

_HEADER = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,"
    "Publisher,Binding,Number of Pages,Year Published,Original Publication Year,"
    "Date Read,Date Added,Bookshelves,Bookshelves with positions,Exclusive Shelf,"
    "My Review,Spoiler,Private Notes,Read Count,Owned Copies"
)


def _csv(*data_rows: str) -> io.StringIO:
    return io.StringIO("\n".join([_HEADER, *data_rows]) + "\n")


def test_parses_escaped_isbn13_and_core_fields() -> None:
    row = (
        '37330,Hijos de la medianoche,Salman Rushdie,"Rushdie, Salman",Miguel Sáenz,'
        '"=""8497934326""","=""9788497934329""",4,DeBolsillo,Mass Market Paperback,798,'
        "2005,1981,2021/10/29,2021/06/24,,,read,,,,1,0"
    )
    [entry] = parse_goodreads_csv(_csv(row))
    assert entry.source_book_id == "37330"
    assert entry.title == "Hijos de la medianoche"
    assert entry.author == "Salman Rushdie"
    # Excel-escaped ="9788497934329" → clean ISBN-13.
    assert entry.isbn_13 == "9788497934329"
    assert entry.shelf is Shelf.READ
    assert entry.rating == 4
    assert entry.date_read == date(2021, 10, 29)
    assert entry.date_added == date(2021, 6, 24)


def test_falls_back_to_isbn10_when_no_isbn13() -> None:
    # ISBN13 blank, ISBN-10 present → convert to ISBN-13 (978 prefix).
    row = '99,Some Book,Author Name,"Name, Author",,"=""8497934326""","=""""",0,,,,,,,2024/01/02,,,to-read,,,,0,0'
    [entry] = parse_goodreads_csv(_csv(row))
    assert entry.isbn_13 == "9788497934329"
    # Rating 0 (Goodreads "unrated") → None.
    assert entry.rating is None
    assert entry.shelf is Shelf.TO_READ


def test_handles_missing_isbn_and_dates() -> None:
    row = '7,Untitled-ish,,,,"=""""","=""""",3,,,,,,,,,,currently-reading,,,,0,0'
    [entry] = parse_goodreads_csv(_csv(row))
    assert entry.isbn_13 is None
    assert entry.author is None
    assert entry.date_read is None
    assert entry.shelf is Shelf.CURRENTLY_READING
    assert entry.rating == 3


def test_skips_rows_without_title_or_book_id() -> None:
    good = '1,Real Title,A,"A, A",,"=""""","=""""",0,,,,,,,,,,read,,,,0,0'
    no_title = '2,,A,"A, A",,"=""""","=""""",0,,,,,,,,,,read,,,,0,0'
    entries = parse_goodreads_csv(_csv(good, no_title))
    assert [e.source_book_id for e in entries] == ["1"]


def test_unknown_shelf_defaults_to_to_read() -> None:
    row = '3,Weird Shelf,A,"A, A",,"=""""","=""""",0,,,,,,,,,,want-to-read-someday,,,,0,0'
    [entry] = parse_goodreads_csv(_csv(row))
    assert entry.shelf is Shelf.TO_READ
