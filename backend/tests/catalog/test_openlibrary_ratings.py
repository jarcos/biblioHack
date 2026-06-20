"""Open Library ratings parser (C4) — pure, no network."""

from __future__ import annotations

from bibliohack.catalog.infrastructure.openlibrary.ratings import parse_rating_count


def test_parses_count_from_first_doc() -> None:
    assert parse_rating_count({"numFound": 1, "docs": [{"ratings_count": 42}]}) == 42


def test_missing_count_is_zero() -> None:
    assert parse_rating_count({"numFound": 1, "docs": [{}]}) == 0


def test_no_docs_is_zero() -> None:
    assert parse_rating_count({"numFound": 0, "docs": []}) == 0
    assert parse_rating_count({}) == 0


def test_non_numeric_count_is_zero() -> None:
    assert parse_rating_count({"docs": [{"ratings_count": "lots"}]}) == 0


def test_negative_count_clamped_to_zero() -> None:
    assert parse_rating_count({"docs": [{"ratings_count": -3}]}) == 0
