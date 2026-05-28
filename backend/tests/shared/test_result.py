"""Tests for the Result type."""

from __future__ import annotations

from bibliohack.shared.application import Err, Ok, Result


def test_ok_carries_value() -> None:
    result: Result[int, str] = Ok(value=42)
    match result:
        case Ok(value):
            assert value == 42
        case Err():
            raise AssertionError("expected Ok")


def test_err_carries_error() -> None:
    result: Result[int, str] = Err(error="boom")
    match result:
        case Ok():
            raise AssertionError("expected Err")
        case Err(error):
            assert error == "boom"


def test_ok_and_err_are_not_equal() -> None:
    assert Ok(value=1) != Err(error=1)
