"""Tests for the Isbn value object."""

from __future__ import annotations

import pytest

from bibliohack.catalog.domain import Isbn


def test_clean_isbn13() -> None:
    isbn = Isbn(value="9788491992080")
    assert isbn.value == "9788491992080"
    assert isbn.is_isbn13
    assert not isbn.is_isbn10


def test_clean_isbn10() -> None:
    isbn = Isbn(value="0140449132")
    assert isbn.value == "0140449132"
    assert isbn.is_isbn10
    assert not isbn.is_isbn13


def test_isbn10_with_trailing_x() -> None:
    # 'X' is a legitimate ISBN-10 check digit (representing 10).
    isbn = Isbn(value="080442957X")
    assert isbn.value == "080442957X"


def test_hyphens_and_spaces_are_stripped() -> None:
    isbn = Isbn(value="978-84-9199-208-0")
    assert isbn.value == "9788491992080"


def test_isbn_prefix_is_stripped() -> None:
    isbn = Isbn(value="ISBN: 978-84-9199-208-0")
    assert isbn.value == "9788491992080"


def test_lowercase_x_is_normalised_to_upper() -> None:
    isbn = Isbn(value="080442957x")
    assert isbn.value == "080442957X"


@pytest.mark.parametrize("bad", ["", "123", "not-an-isbn", "12345", "12345678901234"])
def test_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError, match="ISBN"):
        Isbn(value=bad)


def test_equality_by_value() -> None:
    assert Isbn(value="9788491992080") == Isbn(value="978-84-9199-208-0")
