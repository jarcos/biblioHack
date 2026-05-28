"""Tests for the TITN value object."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bibliohack.catalog.domain.titn import Titn


def test_construction_with_valid_positive_int() -> None:
    titn = Titn(value=42)
    assert titn.value == 42
    assert int(titn) == 42
    assert str(titn) == "42"


@pytest.mark.parametrize("bad", [0, -1, -1000])
def test_zero_or_negative_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        Titn(value=bad)


def test_equality_is_by_value() -> None:
    assert Titn(value=1) == Titn(value=1)
    assert Titn(value=1) != Titn(value=2)
    assert hash(Titn(value=99)) == hash(Titn(value=99))


def test_total_ordering_works() -> None:
    # `order=True` on the dataclass gives us lt/gt/le/ge for free,
    # which is useful when iterating the TITN range in M1.
    assert Titn(value=1) < Titn(value=2)
    assert sorted([Titn(3), Titn(1), Titn(2)]) == [Titn(1), Titn(2), Titn(3)]


@given(st.integers(min_value=1, max_value=10_000_000))
def test_round_trip_through_int_and_str(value: int) -> None:
    titn = Titn(value=value)
    assert int(titn) == value
    assert str(titn) == str(value)
