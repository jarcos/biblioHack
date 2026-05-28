"""Tests for the BibliographicRecord aggregate."""

from __future__ import annotations

import pytest

from bibliohack.catalog.domain import (
    BibliographicRecord,
    BibliographicRecordId,
    Contributor,
    ContributorRole,
    Isbn,
    Titn,
)


def _basic() -> BibliographicRecord:
    return BibliographicRecord(
        entity_id=BibliographicRecordId.new(),
        titn=Titn(1),
        title="Cien años de soledad",
        source_url="https://example.test/?TITN=1",
        source_hash=b"\x00" * 32,
    )


def test_constructor_strips_title_whitespace() -> None:
    rec = BibliographicRecord(
        entity_id=BibliographicRecordId.new(),
        titn=Titn(7),
        title="  El Quijote  ",
        source_url="https://example.test/?TITN=7",
        source_hash=b"\x00" * 32,
    )
    assert rec.title == "El Quijote"


def test_blank_title_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty title"):
        BibliographicRecord(
            entity_id=BibliographicRecordId.new(),
            titn=Titn(1),
            title="   ",
            source_url="x",
            source_hash=b"",
        )


@pytest.mark.parametrize("year", [1399, 2101, -1, 9999])
def test_implausible_pub_year_rejected(year: int) -> None:
    with pytest.raises(ValueError, match="Implausible publication year"):
        BibliographicRecord(
            entity_id=BibliographicRecordId.new(),
            titn=Titn(1),
            title="x",
            source_url="x",
            source_hash=b"",
            pub_year=year,
        )


def test_factory_assigns_fresh_id() -> None:
    a = BibliographicRecord.new_from_scrape(
        titn=Titn(1),
        title="x",
        source_url="https://example.test/?TITN=1",
        source_hash=b"\x00" * 32,
    )
    b = BibliographicRecord.new_from_scrape(
        titn=Titn(2),
        title="y",
        source_url="https://example.test/?TITN=2",
        source_hash=b"\x00" * 32,
    )
    assert a.id != b.id


def test_primary_author_picks_first_author_role() -> None:
    rec = _basic()
    rec.contributors = [
        Contributor(name="Grossman, Edith", role=ContributorRole.TRANSLATOR),
        Contributor(name="García Márquez, Gabriel", role=ContributorRole.AUTHOR),
        Contributor(name="Doe, Jane", role=ContributorRole.AUTHOR),
    ]
    assert rec.primary_author is not None
    assert rec.primary_author.name == "García Márquez, Gabriel"


def test_primary_author_none_when_no_authors() -> None:
    rec = _basic()
    rec.contributors = [Contributor(name="Editor", role=ContributorRole.EDITOR)]
    assert rec.primary_author is None


def test_touch_bumps_last_seen_only() -> None:
    rec = _basic()
    original_first = rec.first_seen_at
    rec.touch()
    assert rec.first_seen_at == original_first
    assert rec.last_seen_at >= original_first


def test_apply_refresh_preserves_identity() -> None:
    rec = _basic()
    original_id = rec.id
    original_titn = rec.titn
    original_first_seen = rec.first_seen_at

    rec.apply_refresh(
        title="Cien años de soledad (edición conmemorativa)",
        subtitle="50 aniversario",
        document_type="Monografías",
        language="spa",
        pub_year=2017,
        publisher="Real Academia Española",
        summary=None,
        contributors=[Contributor(name="García Márquez, Gabriel")],
        subjects=["Novela hispanoamericana"],
        isbns=[Isbn(value="9788491992080")],
        source_hash=b"\xff" * 32,
    )

    assert rec.id == original_id
    assert rec.titn == original_titn
    assert rec.first_seen_at == original_first_seen
    assert rec.title == "Cien años de soledad (edición conmemorativa)"
    assert rec.pub_year == 2017
    assert rec.isbns[0].value == "9788491992080"
