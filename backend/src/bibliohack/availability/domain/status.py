"""Availability status — domain enum + OPAC mapping.

The AbsysNET OPAC reports per-ejemplar status as a free-text Spanish
phrase on the `<tr data-disp="…">` attribute (and visibly in the row's
"Disponibilidad" cell). Examples observed on the live RBPA:

- "Disponible"       — on the shelf, can be borrowed
- "Prestado"         — currently loaned out
- "Reservado"        — reserved for another user, not borrowable
- "No disponible"    — not for loan (rare; e.g. damaged, in process)
- "En inventario"    — being inventoried, not currently lendable
- "Excluido"         — removed from circulation

We map these to a small closed enum so downstream code reasons about
"can I borrow this now?" without parsing Spanish strings. The mapping
is deliberately defensive: any value we haven't seen lands in
:class:`AvailabilityStatus.UNKNOWN` and the raw string is preserved on
the snapshot for later analysis.
"""

from __future__ import annotations

from enum import StrEnum


class AvailabilityStatus(StrEnum):
    """Closed set of availability states the rest of the app reasons about."""

    AVAILABLE = "available"
    LOANED = "loaned"
    RESERVED = "reserved"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


# Lowercase + stripped lookup table. Keys are normalised forms of the OPAC's
# data-disp strings; values are the domain status. Anything not in the table
# falls back to UNKNOWN — we keep the raw string on the snapshot so we can
# inspect drift later.
_MAPPING: dict[str, AvailabilityStatus] = {
    "disponible": AvailabilityStatus.AVAILABLE,
    "prestado": AvailabilityStatus.LOANED,
    "prestada": AvailabilityStatus.LOANED,
    "prestados": AvailabilityStatus.LOANED,
    "reservado": AvailabilityStatus.RESERVED,
    "reservada": AvailabilityStatus.RESERVED,
    # "En inventario", "No disponible", "Excluido", "En proceso", "En reparación"
    # all mean: not lendable right now. Group them under UNAVAILABLE.
    "en inventario": AvailabilityStatus.UNAVAILABLE,
    "no disponible": AvailabilityStatus.UNAVAILABLE,
    "excluido": AvailabilityStatus.UNAVAILABLE,
    "en proceso": AvailabilityStatus.UNAVAILABLE,
    "en reparación": AvailabilityStatus.UNAVAILABLE,
    "en reparacion": AvailabilityStatus.UNAVAILABLE,
}


def map_opac_status(raw: str | None) -> AvailabilityStatus:
    """Map the OPAC's literal disponibilidad string to the domain enum.

    ``None`` or empty/whitespace input → :data:`AvailabilityStatus.UNKNOWN`.
    Unknown values also fall back to UNKNOWN (callers can audit via the
    raw-text column on the snapshot).
    """
    if not raw:
        return AvailabilityStatus.UNKNOWN
    key = raw.strip().lower()
    if not key:
        return AvailabilityStatus.UNKNOWN
    return _MAPPING.get(key, AvailabilityStatus.UNKNOWN)
