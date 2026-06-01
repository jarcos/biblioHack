"""Tests for the literary-profile classifier (audience + literary form).

The keep/hide decision biblioHack makes hinges on this, so the rules are
pinned tightly: tejuelo prefixes (validated against the titn_1 fixture),
CDU ranges, multi-signal resolution, and the default-scope predicate.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bibliohack.catalog.domain.literary_profile import (
    Audience,
    LiteraryForm,
    LiteraryProfile,
    SearchScope,
    classify_literary_profile,
    default_scope_audiences,
    default_scope_forms,
)

# ───────────────────────────────────────────────────────────────
# Signature (tejuelo) signal
# ───────────────────────────────────────────────────────────────


class TestSignatureSignal:
    @pytest.mark.parametrize(
        ("signature", "audience", "form"),
        [
            ("N ARS roh", Audience.ADULT, LiteraryForm.LITERARY),  # adult narrative
            ("N MUR cor", Audience.ADULT, LiteraryForm.LITERARY),
            ("P GAR can", Audience.ADULT, LiteraryForm.LITERARY),  # poesía
            ("T LOR bod", Audience.ADULT, LiteraryForm.LITERARY),  # teatro
            ("J-N SAL cab", Audience.YOUTH, LiteraryForm.LITERARY),  # juvenil narrative
            ("I-N END fin", Audience.CHILDREN, LiteraryForm.LITERARY),  # infantil narrative
        ],
    )
    def test_letter_sections_classify(
        self, signature: str, audience: Audience, form: LiteraryForm
    ) -> None:
        profile = classify_literary_profile(classification=None, signatures=[signature])
        assert profile.audience is audience
        assert profile.form is form

    def test_bare_infantil_is_children_with_unknown_form(self) -> None:
        # "I" without a narrative arm: audience is clear, form is not.
        profile = classify_literary_profile(classification=None, signatures=["I 087 cue"])
        assert profile.audience is Audience.CHILDREN
        assert profile.form is LiteraryForm.UNKNOWN

    @pytest.mark.parametrize("signature", ["3-B-522", "UNI 6383", "", "   ", "R DIC"])
    def test_topographic_or_uninformative_signatures_yield_nothing(self, signature: str) -> None:
        # Deposit / reference / unknown shelf codes carry no audience or form.
        profile = classify_literary_profile(classification=None, signatures=[signature])
        assert profile.audience is Audience.UNKNOWN
        assert profile.form is LiteraryForm.UNKNOWN


# ───────────────────────────────────────────────────────────────
# CDU / UDC signal
# ───────────────────────────────────────────────────────────────


class TestCduSignal:
    @pytest.mark.parametrize(
        "cdu",
        ['821.134.2-1"19"', "821.134.2-3", "82-3", "860-3", "821.111-31"],
    )
    def test_literature_classes_are_literary(self, cdu: str) -> None:
        profile = classify_literary_profile(classification=cdu, signatures=[])
        assert profile.form is LiteraryForm.LITERARY

    @pytest.mark.parametrize(
        "cdu",
        ["94(460)", "551.5", "327", "0", "159.9", "811.134.2", "642"],
    )
    def test_non_literature_classes_are_nonfiction(self, cdu: str) -> None:
        # Note 811 (linguistics) is non-fiction even though it starts with 8.
        profile = classify_literary_profile(classification=cdu, signatures=[])
        assert profile.form is LiteraryForm.NONFICTION

    def test_literary_criticism_is_nonfiction(self) -> None:
        profile = classify_literary_profile(classification="821.134.2.09", signatures=[])
        assert profile.form is LiteraryForm.NONFICTION

    @pytest.mark.parametrize("cdu", ["821.134.2-93", "087.5", "82-93"])
    def test_children_youth_markers_set_children(self, cdu: str) -> None:
        profile = classify_literary_profile(classification=cdu, signatures=[])
        assert profile.audience is Audience.CHILDREN

    def test_non_numeric_classification_is_ignored(self) -> None:
        profile = classify_literary_profile(classification="N/A", signatures=[])
        assert profile == LiteraryProfile()


# ───────────────────────────────────────────────────────────────
# Multi-signal resolution
# ───────────────────────────────────────────────────────────────


class TestResolution:
    def test_adult_evidence_wins_over_youth(self) -> None:
        # A title shelved in both the adult and the juvenil room is gettable
        # by an adult, so ADULT wins.
        profile = classify_literary_profile(
            classification=None, signatures=["N ARS roh", "J-N SAL cab"]
        )
        assert profile.audience is Audience.ADULT

    def test_literary_evidence_wins_over_nonfiction(self) -> None:
        # A strong real-world narrative shelf mark beats an ambiguous CDU.
        profile = classify_literary_profile(classification="94(460)", signatures=["N ABC xyz"])
        assert profile.form is LiteraryForm.LITERARY

    def test_real_titn_1_signals_resolve_to_adult_literary(self) -> None:
        # The canonical fixture: CDU 821.134.2-1 (Spanish poetry) + copies in
        # adult (N), juvenil (J-N) and two deposit shelves.
        profile = classify_literary_profile(
            classification='821.134.2-1"19"',
            signatures=["3-B-522", "J-N SAL cab", "N ARS roh", "UNI 6383"],
        )
        assert profile.audience is Audience.ADULT
        assert profile.form is LiteraryForm.LITERARY
        assert profile.in_default_scope is True

    def test_pure_childrens_book_is_excluded_from_default_scope(self) -> None:
        profile = classify_literary_profile(classification="087.5", signatures=["I CUE per"])
        assert profile.audience is Audience.CHILDREN
        assert profile.in_default_scope is False

    def test_no_signals_is_unknown_and_stays_in_default_scope(self) -> None:
        profile = classify_literary_profile(classification=None, signatures=[])
        assert profile == LiteraryProfile()
        assert profile.audience is Audience.UNKNOWN
        assert profile.form is LiteraryForm.UNKNOWN
        assert profile.in_default_scope is True


# ───────────────────────────────────────────────────────────────
# Default-scope predicate + helpers
# ───────────────────────────────────────────────────────────────


class TestDefaultScope:
    @pytest.mark.parametrize(
        ("audience", "form", "expected"),
        [
            (Audience.ADULT, LiteraryForm.LITERARY, True),
            (Audience.ADULT, LiteraryForm.UNKNOWN, True),
            (Audience.UNKNOWN, LiteraryForm.LITERARY, True),
            (Audience.UNKNOWN, LiteraryForm.UNKNOWN, True),
            (Audience.ADULT, LiteraryForm.NONFICTION, False),
            (Audience.YOUTH, LiteraryForm.LITERARY, False),
            (Audience.CHILDREN, LiteraryForm.LITERARY, False),
            (Audience.CHILDREN, LiteraryForm.NONFICTION, False),
        ],
    )
    def test_in_default_scope(self, audience: Audience, form: LiteraryForm, expected: bool) -> None:
        assert LiteraryProfile(audience=audience, form=form).in_default_scope is expected

    def test_scope_helpers_match_the_predicate(self) -> None:
        audiences = default_scope_audiences()
        forms = default_scope_forms()
        assert set(audiences) == {Audience.ADULT.value, Audience.UNKNOWN.value}
        assert set(forms) == {LiteraryForm.LITERARY.value, LiteraryForm.UNKNOWN.value}

    def test_search_scope_values(self) -> None:
        assert SearchScope.LITERARY.value == "literary"
        assert SearchScope.ALL.value == "all"


# ───────────────────────────────────────────────────────────────
# Property-based: never crash, always return valid enums
# ───────────────────────────────────────────────────────────────


@given(
    classification=st.none() | st.text(max_size=40),
    signatures=st.lists(st.none() | st.text(max_size=30), max_size=8),
)
def test_classify_is_total_and_well_typed(
    classification: str | None, signatures: list[str | None]
) -> None:
    profile = classify_literary_profile(classification=classification, signatures=signatures)
    assert isinstance(profile.audience, Audience)
    assert isinstance(profile.form, LiteraryForm)
    # The predicate must be computable for every possible profile.
    assert isinstance(profile.in_default_scope, bool)
