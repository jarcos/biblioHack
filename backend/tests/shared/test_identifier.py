"""Tests for the shared Identifier base class."""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

from bibliohack.shared.domain import Identifier


@dataclass(frozen=True, slots=True)
class _ExampleId(Identifier):
    """A concrete Identifier subclass used only for these tests."""


def test_new_returns_unique_values() -> None:
    ids = {_ExampleId.new() for _ in range(100)}
    assert len(ids) == 100


def test_from_string_round_trip() -> None:
    original = _ExampleId.new()
    parsed = _ExampleId.from_string(str(original))
    assert parsed == original


def test_equality_is_by_value() -> None:
    one = _ExampleId.new()
    two = _ExampleId(value=one.value)
    assert one == two
    assert hash(one) == hash(two)


@given(st.uuids())
def test_construction_from_uuid_is_idempotent(raw_uuid: object) -> None:
    # `st.uuids` returns uuid.UUID instances.
    from uuid import UUID  # noqa: PLC0415  (local import keeps the test scope tight)

    assert isinstance(raw_uuid, UUID)
    ident = _ExampleId(value=raw_uuid)
    assert ident.value == raw_uuid
    assert _ExampleId.from_string(str(ident)) == ident
