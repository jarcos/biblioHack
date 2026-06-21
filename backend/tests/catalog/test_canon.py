"""Canon domain + Wikidata query/parse — pure, no DB or network."""

from __future__ import annotations

import pytest

from bibliohack.catalog.domain.canon import (
    AcquireStatus,
    CanonMatchVia,
    CanonSeedWork,
    CanonSource,
)
from bibliohack.catalog.domain.isbn import isbn10_to_13
from bibliohack.catalog.infrastructure.wikidata.query import (
    build_canon_query,
    next_cursor,
    parse_bindings,
)


def _work(**kw: object) -> CanonSeedWork:
    base: dict[str, object] = {
        "source": CanonSource.WIKIDATA,
        "source_ref": "Q123",
        "title": "Cien años de soledad",
    }
    base.update(kw)
    return CanonSeedWork(**base)  # type: ignore[arg-type]


# --- CanonSeedWork normalisation --------------------------------------------


def test_isbn10_is_normalised_to_isbn13() -> None:
    work = _work(isbn13=["0-306-40615-2"])  # a valid ISBN-10
    assert work.isbn13 == (isbn10_to_13("0306406152"),)
    assert all(len(i) == 13 for i in work.isbn13)


def test_isbns_are_deduped_order_stable() -> None:
    work = _work(isbn13=["978-84-376-0494-7", "9788437604947", "garbage"])
    assert work.isbn13 == ("9788437604947",)  # deduped, junk dropped


def test_sentinel_pub_year_becomes_none() -> None:
    assert _work(pub_year=9999).pub_year is None
    assert _work(pub_year=0).pub_year is None
    assert _work(pub_year=1967).pub_year == 1967


def test_future_pub_year_becomes_none() -> None:
    """A seed year well beyond next year (2033) is a source-data error and is
    stored as unknown, mirroring the catalogue parser's plausibility band."""
    assert _work(pub_year=2033).pub_year is None


def test_author_blank_becomes_none_and_is_stripped() -> None:
    assert _work(author="   ").author is None
    assert _work(author="  García Márquez ").author == "García Márquez"


def test_awards_deduped_case_insensitively_order_stable() -> None:
    work = _work(awards=["Premio Nobel", "premio nobel", " ", "Cervantes"])
    assert work.awards == ("Premio Nobel", "Cervantes")


def test_notability_is_clamped_non_negative() -> None:
    assert _work(notability=-5).notability == 0
    assert _work(notability=42).notability == 42


def test_empty_title_or_ref_is_rejected() -> None:
    with pytest.raises(ValueError, match="title"):
        _work(title="   ")
    with pytest.raises(ValueError, match="source_ref"):
        _work(source_ref="")


def test_enums_store_expected_string_values() -> None:
    assert str(CanonSource.WIKIDATA) == "wikidata"
    assert str(AcquireStatus.UNCHECKED) == "unchecked"
    assert str(CanonMatchVia.TITLE_AUTHOR) == "title_author"


# --- SPARQL query builder ----------------------------------------------------


def test_query_has_core_clauses_and_pagination() -> None:
    q = build_canon_query(min_sitelinks=12, limit=10)
    assert "wd:Q7725634" in q  # literary work
    assert "wikibase:sitelinks ?sitelinks" in q
    assert "?sitelinks >= 12" in q
    assert "LIMIT 10" in q
    assert "OFFSET" not in q  # keyset, not offset
    assert "ORDER BY ?work" in q  # stable, cheap pagination


def test_first_page_has_no_seek_filter() -> None:
    q = build_canon_query(limit=10)
    assert "FILTER(STR(?work) >" not in q


def test_keyset_seek_filters_past_the_cursor() -> None:
    q = build_canon_query(limit=10, after_qid="Q480")
    assert 'FILTER(STR(?work) > "http://www.wikidata.org/entity/Q480")' in q
    assert "OFFSET" not in q
    assert "ORDER BY ?work" in q  # seek + order share the same lexical ordering


def test_default_query_includes_award_union() -> None:
    q = build_canon_query()
    assert "UNION" in q
    assert "wdt:P166" in q  # award branch present


def test_spanish_only_drops_award_union() -> None:
    q = build_canon_query(spanish_only=True)
    assert "UNION" not in q
    assert "wdt:P407 wd:Q1321" in q  # requires Spanish


# --- SPARQL result parsing ---------------------------------------------------


def _cell(value: str) -> dict[str, str]:
    return {"value": value}


def test_parse_bindings_maps_a_full_row() -> None:
    sep = "␟"
    rows = [
        {
            "work": _cell("http://www.wikidata.org/entity/Q480"),
            "workLabel": _cell("Cien años de soledad"),
            "authorLabel": _cell("Gabriel García Márquez"),
            "pubYear": _cell("1967"),
            "isbn13s": _cell("9788437604947"),
            "isbn10s": _cell(f"0306406152{sep}garbage"),
            "awards": _cell(f"Premio Rómulo Gallegos{sep}Premio Rómulo Gallegos"),
            "notability": _cell("57"),
        }
    ]
    [work] = parse_bindings(rows)
    assert work.source is CanonSource.WIKIDATA
    assert work.source_ref == "Q480"
    assert work.title == "Cien años de soledad"
    assert work.author == "Gabriel García Márquez"
    assert work.pub_year == 1967
    assert "9788437604947" in work.isbn13
    assert isbn10_to_13("0306406152") in work.isbn13
    assert work.awards == ("Premio Rómulo Gallegos",)
    assert work.notability == 57


def test_parse_bindings_skips_unlabelled_rows() -> None:
    # workLabel still equal to the QID => label service found no name => skip.
    rows = [
        {
            "work": _cell("http://www.wikidata.org/entity/Q999"),
            "workLabel": _cell("Q999"),
        },
        {"workLabel": _cell("No work uri")},  # missing ?work
    ]
    assert parse_bindings(rows) == []


# --- keyset cursor -----------------------------------------------------------


def test_next_cursor_returns_max_work_qid() -> None:
    rows = [
        {"work": _cell("http://www.wikidata.org/entity/Q480")},
        {"work": _cell("http://www.wikidata.org/entity/Q999")},
        {"work": _cell("http://www.wikidata.org/entity/Q700")},
    ]
    # Max by IRI string (the same ordering ORDER BY ?work uses), not row order.
    assert next_cursor(rows) == "Q999"


def test_next_cursor_advances_past_an_unlabelled_boundary_row() -> None:
    # The largest work on the page is one parse_bindings would drop (label==QID).
    # The cursor must still advance to it, or the seek would re-request it forever.
    rows = [
        {
            "work": _cell("http://www.wikidata.org/entity/Q500"),
            "workLabel": _cell("A real title"),
        },
        {
            "work": _cell("http://www.wikidata.org/entity/Q999"),
            "workLabel": _cell("Q999"),  # dropped by parse_bindings
        },
    ]
    assert parse_bindings(rows)  # the labelled row survives
    assert next_cursor(rows) == "Q999"  # cursor still advances to the max


def test_next_cursor_none_when_no_work_uri() -> None:
    assert next_cursor([{"workLabel": _cell("no uri here")}]) is None
    assert next_cursor([]) is None
