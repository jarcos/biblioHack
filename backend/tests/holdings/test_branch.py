"""Tests for the Branch entity and BranchCode value object."""

from __future__ import annotations

import pytest

from bibliohack.holdings.domain import Branch, BranchCode


def test_branch_code_round_trips() -> None:
    code = BranchCode(value="21001")
    assert code.value == "21001"
    assert str(code) == "21001"


def test_branch_code_rejects_blank() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        BranchCode(value="   ")


def test_branch_code_equality_by_value() -> None:
    assert BranchCode(value="21001") == BranchCode(value="21001")
    assert hash(BranchCode(value="21001")) == hash(BranchCode(value="21001"))


def test_branch_construction_and_id_exposure() -> None:
    branch = Branch(
        code=BranchCode(value="21001"),
        name="Biblioteca Provincial de Huelva",
        municipality="Huelva",
        province="Huelva",
    )
    assert branch.code.value == "21001"
    assert branch.id == BranchCode(value="21001")
    assert branch.name == "Biblioteca Provincial de Huelva"
    assert branch.is_active is True


def test_branch_blank_name_rejected() -> None:
    with pytest.raises(ValueError, match="name must not be blank"):
        Branch(code=BranchCode(value="21001"), name="  ")


def test_two_branches_with_same_code_are_equal() -> None:
    a = Branch(code=BranchCode(value="21001"), name="Huelva")
    b = Branch(code=BranchCode(value="21001"), name="Huelva Provincial")
    # Equality is by identity (the BranchCode), not by state.
    assert a == b


def test_branch_geo_fields_default_to_none_and_has_geo_is_false() -> None:
    branch = Branch(code=BranchCode(value="AL03"), name="Adra")
    assert branch.lat is None
    assert branch.lng is None
    assert branch.address is None
    assert branch.has_geo is False


def test_branch_has_geo_true_only_with_both_coordinates() -> None:
    geocoded = Branch(
        code=BranchCode(value="AL03"),
        name="Adra",
        municipality="Adra",
        province="Almería",
        lat=36.7497,
        lng=-3.0206,
    )
    assert geocoded.has_geo is True
    # A half-set coordinate pair is not usable for proximity sorting.
    half = Branch(code=BranchCode(value="AL04"), name="Berja", lat=36.85)
    assert half.has_geo is False
