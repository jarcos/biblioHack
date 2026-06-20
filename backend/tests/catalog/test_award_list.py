"""Curated award fallback (C4) — AwardListCanonSource."""

from __future__ import annotations

from bibliohack.catalog.domain.canon import CanonSource
from bibliohack.catalog.infrastructure.canon.award_list import (
    AwardListCanonSource,
    award_source_ref,
)


async def _collect(max_works: int | None = None) -> list:
    return [w async for w in AwardListCanonSource().fetch_works(max_works=max_works)]


async def test_yields_award_list_works() -> None:
    works = await _collect()
    assert works  # non-empty curated list
    assert all(w.source is CanonSource.AWARD_LIST for w in works)
    # Every entry carries a stable award: source_ref and a title.
    assert all(w.source_ref.startswith("award:") for w in works)
    assert all(w.title and w.author for w in works)


async def test_source_ref_is_a_stable_ascii_slug() -> None:
    assert (
        award_source_ref("Cien años de soledad", "Gabriel García Márquez")
        == "award:cien-anos-de-soledad--gabriel-garcia-marquez"
    )
    works = await _collect()
    ref = award_source_ref("Cien años de soledad", "Gabriel García Márquez")
    assert any(w.source_ref == ref for w in works)


async def test_source_refs_are_unique() -> None:
    works = await _collect()
    refs = [w.source_ref for w in works]
    assert len(refs) == len(set(refs))


async def test_max_works_caps_output() -> None:
    works = await _collect(max_works=3)
    assert len(works) == 3
