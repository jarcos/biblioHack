"""Unit tests for the OPAC → domain availability status mapping."""

from __future__ import annotations

import pytest

from bibliohack.availability.domain.status import (
    AvailabilityStatus,
    map_opac_status,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Disponible", AvailabilityStatus.AVAILABLE),
        ("disponible", AvailabilityStatus.AVAILABLE),
        ("  DISPONIBLE  ", AvailabilityStatus.AVAILABLE),
        ("Prestado", AvailabilityStatus.LOANED),
        ("prestados", AvailabilityStatus.LOANED),
        ("Reservado", AvailabilityStatus.RESERVED),
        ("En inventario", AvailabilityStatus.UNAVAILABLE),
        ("No disponible", AvailabilityStatus.UNAVAILABLE),
        ("Excluido", AvailabilityStatus.UNAVAILABLE),
        ("En reparación", AvailabilityStatus.UNAVAILABLE),
        # accent-stripped variant we accept defensively
        ("En reparacion", AvailabilityStatus.UNAVAILABLE),
    ],
)
def test_known_opac_strings_map_to_domain_status(raw: str, expected: AvailabilityStatus) -> None:
    assert map_opac_status(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_or_none_maps_to_unknown(raw: str | None) -> None:
    assert map_opac_status(raw) == AvailabilityStatus.UNKNOWN


def test_unrecognised_string_falls_back_to_unknown() -> None:
    # If the OPAC ever invents a new disponibilidad value, we keep working
    # — the persistence layer still captures the raw string for audit.
    assert map_opac_status("Cosa rarísima nueva") == AvailabilityStatus.UNKNOWN


def test_status_enum_values_are_stable_strings() -> None:
    # We persist these as text, so the wire format must be the lower-case
    # short form. Lock it down here so a typo can't silently break stored
    # rows on a future refactor.
    assert AvailabilityStatus.AVAILABLE.value == "available"
    assert AvailabilityStatus.LOANED.value == "loaned"
    assert AvailabilityStatus.RESERVED.value == "reserved"
    assert AvailabilityStatus.UNAVAILABLE.value == "unavailable"
    assert AvailabilityStatus.UNKNOWN.value == "unknown"
