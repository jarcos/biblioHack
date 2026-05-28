"""Tests for the Contributor value object."""

from __future__ import annotations

import pytest

from bibliohack.catalog.domain import Contributor, ContributorRole


def test_default_role_is_author() -> None:
    c = Contributor(name="García Márquez, Gabriel")
    assert c.role is ContributorRole.AUTHOR


def test_explicit_role() -> None:
    c = Contributor(name="Grossman, Edith", role=ContributorRole.TRANSLATOR)
    assert c.role is ContributorRole.TRANSLATOR


def test_internal_whitespace_collapses() -> None:
    c = Contributor(name="  García   Márquez,    Gabriel  ")
    assert c.name == "García Márquez, Gabriel"


def test_blank_name_rejected() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        Contributor(name="   ")


def test_equality_is_by_value() -> None:
    a = Contributor(name="Cervantes")
    b = Contributor(name="Cervantes")
    assert a == b
    assert hash(a) == hash(b)
