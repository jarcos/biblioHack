"""Unit tests for the CDU/tejuelo genre derivation (catalog navigator Tier B)."""

from __future__ import annotations

import pytest

from bibliohack.catalog.domain.literary_profile import Genre, derive_genre


@pytest.mark.parametrize(
    ("classification", "expected"),
    [
        ('821.134.2-1"19"', Genre.POETRY),
        ("821.134.2-2", Genre.DRAMA),
        ('821.134.2-31"20"', Genre.NARRATIVE),
        ("821.111-3", Genre.NARRATIVE),
        ("860-4", Genre.ESSAY),  # legacy Spanish-literature class
        ("741.5", Genre.COMIC),
        ("741.52", Genre.COMIC),
        ("82-93", Genre.UNKNOWN),  # infantil marker, not a form division 1-4
        ("94(460)", Genre.UNKNOWN),  # history — not literature
        ("811.134.2", Genre.UNKNOWN),  # linguistics — 81, not 82/86
        (None, Genre.UNKNOWN),
        ("", Genre.UNKNOWN),
    ],
)
def test_genre_from_cdu(classification: str | None, expected: Genre) -> None:
    assert derive_genre(classification=classification) is expected


@pytest.mark.parametrize(
    ("signatures", "expected"),
    [
        (["N ARS roh"], Genre.NARRATIVE),
        (["P GAR lor"], Genre.POETRY),
        (["T BUE vid"], Genre.DRAMA),
        (["J-N SAL cab"], Genre.NARRATIVE),  # juvenil narrativa arm
        (["C MOO wat"], Genre.COMIC),
        (["3-B-522"], Genre.UNKNOWN),  # topographic code — no signal
        (["UNI 6383", None, ""], Genre.UNKNOWN),
        (["CO 123"], Genre.UNKNOWN),  # "CO…" is not the cómic section
    ],
)
def test_genre_from_signatures(signatures: list[str | None], expected: Genre) -> None:
    assert derive_genre(classification=None, signatures=signatures) is expected


def test_cdu_wins_over_signatures() -> None:
    # The cataloguer says poetry; a copy happens to sit in the narrative room.
    genre = derive_genre(classification="821.134.2-1", signatures=["N ARS roh"])
    assert genre is Genre.POETRY


def test_signature_conflict_prefers_narrative() -> None:
    genre = derive_genre(classification=None, signatures=["P GAR lor", "N ARS roh"])
    assert genre is Genre.NARRATIVE
