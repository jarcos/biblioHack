"""Curated award-winner seed — the marquee-names fallback (canon C4).

A small, hand-kept list of canonical Spanish-language works by major literary
award (Nobel, Cervantes). It exists so the canon seed *guarantees* the marquee
names even if a Wikidata edge is missing or the WDQS notability floor filters a
work out (see ``docs/design/canon-import.md`` → "Curated award seed"). These are
facts (winners/works), not copyrightable content.

Implemented as a typed Python list rather than the design's suggested YAML so it
needs no extra dependency and is type-checked — functionally identical for a
small curated set. It plugs into the same :class:`CanonSeedSource` port as the
Wikidata builder, so ``RefreshCanonSeed`` upserts it idempotently by
``(source, source_ref)``; ``source_ref`` is a stable slug of title+author.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from bibliohack.catalog.domain.canon import CanonSeedWork, CanonSource

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_NOBEL = "Premio Nobel de Literatura"
_CERVANTES = "Premio Cervantes"

# (title, author, awards, pub_year|None) — a representative work per laureate.
_AWARD_WORKS: tuple[tuple[str, str, tuple[str, ...], int | None], ...] = (
    # Nobel laureates writing in Spanish, with a representative work.
    ("Platero y yo", "Juan Ramón Jiménez", (_NOBEL,), 1914),
    ("El señor presidente", "Miguel Ángel Asturias", (_NOBEL,), 1946),
    ("Veinte poemas de amor y una canción desesperada", "Pablo Neruda", (_NOBEL,), 1924),
    ("La destrucción o el amor", "Vicente Aleixandre", (_NOBEL,), 1935),
    ("Cien años de soledad", "Gabriel García Márquez", (_NOBEL,), 1967),
    ("La familia de Pascual Duarte", "Camilo José Cela", (_NOBEL,), 1942),
    ("El laberinto de la soledad", "Octavio Paz", (_NOBEL,), 1950),
    ("La ciudad y los perros", "Mario Vargas Llosa", (_NOBEL,), 1963),
    ("Desolación", "Gabriela Mistral", (_NOBEL,), 1922),
    # Cervantes Prize laureates, with a representative work.
    ("Ficciones", "Jorge Luis Borges", (_CERVANTES,), 1944),
    ("El astillero", "Juan Carlos Onetti", (_CERVANTES,), 1961),
    ("La muerte de Artemio Cruz", "Carlos Fuentes", (_CERVANTES,), 1962),
    ("La invención de Morel", "Adolfo Bioy Casares", (_CERVANTES,), 1940),
    ("El camino", "Miguel Delibes", (_CERVANTES,), 1950),
    ("El Jarama", "Rafael Sánchez Ferlosio", (_CERVANTES,), 1955),
    ("Señas de identidad", "Juan Goytisolo", (_CERVANTES,), 1966),
    ("La verdad sobre el caso Savolta", "Eduardo Mendoza", (_CERVANTES,), 1975),
    ("Rayuela", "Julio Cortázar", (), 1963),  # canonical; included for coverage
)


def _slug(text: str) -> str:
    """ASCII, lowercase, hyphen-separated slug — stable across refreshes."""
    normalised = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalised.lower()).strip("-")


def award_source_ref(title: str, author: str) -> str:
    """Stable ``source_ref`` for an award entry: ``award:<title>--<author>``."""
    return f"award:{_slug(title)}--{_slug(author)}"


class AwardListCanonSource:
    """A :class:`CanonSeedSource` over the curated award-winner list (off-OPAC)."""

    async def fetch_works(self, *, max_works: int | None = None) -> AsyncIterator[CanonSeedWork]:
        for i, (title, author, awards, year) in enumerate(_AWARD_WORKS):
            if max_works is not None and i >= max_works:
                return
            yield CanonSeedWork(
                source=CanonSource.AWARD_LIST,
                source_ref=award_source_ref(title, author),
                title=title,
                author=author,
                pub_year=year,
                awards=awards,
                notability=0,
            )
