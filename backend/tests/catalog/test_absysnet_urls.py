"""Tests for AbsysNET URL builders.

URL strings are easy to typo and ugly to debug at 3am, so we cover them with
exact-string assertions. Hypothesis fills in for the wider input space.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from bibliohack.catalog.domain.titn import Titn
from bibliohack.catalog.infrastructure.absysnet.urls import (
    AbsysnetEndpoints,
    SearchField,
    build_expert_url,
    build_new_records_url,
    build_record_url,
    build_search_url,
)

BASE = "https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi"


# ────────────────────────────────────────────────────────────
# build_record_url
# ────────────────────────────────────────────────────────────


def test_record_url_uses_titn_permalink() -> None:
    assert build_record_url(Titn(12345)) == f"{BASE}?TITN=12345"


def test_record_url_accepts_custom_endpoints() -> None:
    custom = AbsysnetEndpoints(base_url="https://example.test/cgi-bin/abnetopac")
    assert build_record_url(Titn(7), endpoints=custom) == (
        "https://example.test/cgi-bin/abnetopac?TITN=7"
    )


@given(st.integers(min_value=1, max_value=10_000_000))
def test_record_url_round_trips_titn(value: int) -> None:
    url = build_record_url(Titn(value))
    assert url.endswith(f"?TITN={value}")


# ────────────────────────────────────────────────────────────
# build_search_url
# ────────────────────────────────────────────────────────────


def test_search_url_simple_title() -> None:
    assert build_search_url(SearchField.TITLE, "cazadores de sombras") == (
        f"{BASE}?ACC=DOSEARCH&xsqf02=cazadores+de+sombras"
    )


def test_search_url_strips_surrounding_whitespace() -> None:
    assert build_search_url(SearchField.AUTHOR, "  Cervantes  ") == (
        f"{BASE}?ACC=DOSEARCH&xsqf03=Cervantes"
    )


def test_search_url_encodes_special_characters() -> None:
    # AbsysNET expects URL-encoded query strings; Spanish characters and
    # punctuation must be percent-encoded, not passed through raw.
    url = build_search_url(SearchField.TITLE, "Niño & Maga: el inicio")
    assert "%26" in url  # &
    assert "%3A" in url  # :
    assert "Ni%C3%B1o" in url  # ñ


def test_search_url_with_branch_filter() -> None:
    url = build_search_url(SearchField.ANY, "test", branch="400/441")
    assert url == f"{BASE}?ACC=DOSEARCH&xsqf01=test&SUBC=400%2F441"


def test_each_search_field_uses_correct_parameter_name() -> None:
    # Guards against an accidental renaming of the enum values, which would
    # silently produce URLs the OPAC doesn't understand.
    fields_and_codes = {
        SearchField.ANY: "xsqf01",
        SearchField.TITLE: "xsqf02",
        SearchField.AUTHOR: "xsqf03",
        SearchField.PUBLISHER: "xsqf04",
        SearchField.SUBJECT: "xsqf05",
        SearchField.COLLECTION: "xsqf06",
        SearchField.DATE_FROM: "xsqf07",
        SearchField.DATE_TO: "xsqf08",
        SearchField.EXPERT: "xsqf99",
    }
    for field, code in fields_and_codes.items():
        url = build_search_url(field, "x")
        assert f"&{code}=x" in url, f"{field.name} did not use {code}"


# ────────────────────────────────────────────────────────────
# build_expert_url
# ────────────────────────────────────────────────────────────


def test_expert_url_encodes_operators() -> None:
    # The expert query language uses `@`, `>`, `=`, etc. — all must encode.
    url = build_expert_url("(@copi>=20200101)")
    assert "xsqf99=" in url
    assert "%40copi" in url
    assert "%3E%3D" in url


def test_expert_url_with_branch() -> None:
    url = build_expert_url("(@fepu>=2015)", branch="441")
    assert "SUBC=441" in url


# ────────────────────────────────────────────────────────────
# build_new_records_url
# ────────────────────────────────────────────────────────────


def test_new_records_url_uses_copi_predicate() -> None:
    url = build_new_records_url(since_yyyymmdd=20260101)
    # `@copi>=20260101` — encoded
    assert "%40copi%3E%3D20260101" in url
    assert url.startswith(f"{BASE}?ACC=DOSEARCH&xsqf99=")
