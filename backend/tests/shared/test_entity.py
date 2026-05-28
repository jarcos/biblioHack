"""Tests for the shared Entity base class."""

from __future__ import annotations

from dataclasses import dataclass

from bibliohack.shared.domain import Entity, Identifier


@dataclass(frozen=True, slots=True)
class _ExampleId(Identifier):
    pass


@dataclass(frozen=True, slots=True)
class _OtherId(Identifier):
    pass


class _Example(Entity[_ExampleId]):
    def __init__(self, entity_id: _ExampleId, name: str) -> None:
        super().__init__(entity_id)
        self.name = name


class _Other(Entity[_OtherId]):
    pass


def test_entities_with_same_id_are_equal_even_if_state_differs() -> None:
    ident = _ExampleId.new()
    a = _Example(ident, name="alpha")
    b = _Example(ident, name="beta")
    assert a == b
    assert hash(a) == hash(b)


def test_entities_with_different_ids_are_not_equal() -> None:
    a = _Example(_ExampleId.new(), name="alpha")
    b = _Example(_ExampleId.new(), name="alpha")
    assert a != b


def test_different_entity_types_with_same_uuid_are_not_equal() -> None:
    # Two different `Identifier` subclasses must never accidentally compare equal,
    # even if their UUID payloads happen to match.
    raw = _ExampleId.new().value
    a = _Example(_ExampleId(value=raw), name="alpha")
    b = _Other(_OtherId(value=raw))
    assert a != b
