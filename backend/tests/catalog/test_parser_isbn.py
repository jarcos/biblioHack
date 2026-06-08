"""Tests for MARC 020 ISBN extraction + ISBN-10→13 normalization.

The covers context is keyed on ISBN-13, and the parser is the only place
ISBNs enter the system — so the normalization is pinned tightly here.
"""

from __future__ import annotations

from bibliohack.catalog.infrastructure.absysnet.parser import parse_record_html


def _html(*isbn_a_values: str, aq: str | None = None) -> str:
    """A minimal record page: a title (required) + js-T020a ISBN spans."""
    spans = "".join(f'<span class="js-T020a">{v}</span>' for v in isbn_a_values)
    if aq is not None:
        spans += f'<span class="js-T020aq">{aq}</span>'
    return (
        '<html><body><span class="js-TITN">1</span>'
        f'<span class="js-T245">Título</span>{spans}</body></html>'
    )


def test_extracts_isbn13_stripping_hyphens() -> None:
    result = parse_record_html(_html("978-84-19942-12-8"))
    assert result.record.isbns == ("9788419942128",)


def test_converts_isbn10_to_isbn13() -> None:
    # Canonical worked example: 0-306-40615-2 → 978-0-306-40615-7.
    result = parse_record_html(_html("0-306-40615-2"))
    assert result.record.isbns == ("9780306406157",)


def test_dedupes_and_drops_unparseable() -> None:
    result = parse_record_html(
        _html("978-84-19942-12-8", "978 84 19942 12 8", "sin isbn", "0306406152")
    )
    # The first two normalize to the same ISBN-13 (deduped); the junk is
    # dropped; the ISBN-10 is converted.
    assert result.record.isbns == ("9788419942128", "9780306406157")


def test_ignores_t020aq_qualifier_span() -> None:
    # The $a+$q variant carries trailing junk; only clean $a is taken.
    result = parse_record_html(_html(aq="978-84-19942-12-8---"))
    assert result.record.isbns == ()
