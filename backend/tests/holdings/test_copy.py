"""Tests for the Copy entity."""

from __future__ import annotations

from bibliohack.catalog.domain import BibliographicRecordId
from bibliohack.holdings.domain import BranchCode, Copy, CopyId


def _copy() -> Copy:
    return Copy(
        entity_id=CopyId.new(),
        record_id=BibliographicRecordId.new(),
        branch_code=BranchCode(value="21001"),
        signature="N MUR cor",
        barcode="0001234567",
    )


def test_copy_construction_defaults_to_active() -> None:
    c = _copy()
    assert c.is_active is True
    assert c.signature == "N MUR cor"
    assert c.barcode == "0001234567"


def test_touch_bumps_last_seen_only() -> None:
    c = _copy()
    original_first = c.first_seen_at
    c.touch()
    assert c.first_seen_at == original_first
    assert c.last_seen_at >= original_first


def test_mark_inactive_flips_is_active() -> None:
    c = _copy()
    assert c.is_active
    c.mark_inactive()
    assert not c.is_active


def test_signature_whitespace_trimmed() -> None:
    c = Copy(
        entity_id=CopyId.new(),
        record_id=BibliographicRecordId.new(),
        branch_code=BranchCode(value="21001"),
        signature="  N MUR cor  ",
    )
    assert c.signature == "N MUR cor"


def test_no_signature_is_none() -> None:
    c = Copy(
        entity_id=CopyId.new(),
        record_id=BibliographicRecordId.new(),
        branch_code=BranchCode(value="21001"),
    )
    assert c.signature is None
    assert c.barcode is None
