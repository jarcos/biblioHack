"""MatchCanonSeed (C1) — ISBN precedence, trigram fallback, bounded sweep."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.catalog.application.ports import CanonSeedRow
from bibliohack.catalog.application.use_cases.match_canon_seed import MatchCanonSeed
from bibliohack.catalog.domain.canon import CanonMatchVia

if TYPE_CHECKING:
    from collections.abc import Sequence


class _FakeRepo:
    """In-memory seed: rows + the mirror's ISBN/title indexes.

    A matched row is removed from the unmatched pool (mirrors the real query's
    ``matched_record_id IS NULL`` filter), so the use case's batch loop ends.
    """

    def __init__(
        self,
        rows: list[CanonSeedRow],
        *,
        isbn_index: dict[str, str] | None = None,
        title_index: dict[str, str] | None = None,
    ) -> None:
        self._unmatched = {r.id: r for r in rows}
        self._isbn = isbn_index or {}
        self._title = title_index or {}
        self.links: list[tuple[str, str, CanonMatchVia]] = []

    async def iter_unmatched(self, *, limit: int, offset: int = 0) -> Sequence[CanonSeedRow]:
        return list(self._unmatched.values())[offset : offset + limit]

    async def match_isbn13(self, isbns: Sequence[str]) -> str | None:
        for isbn in isbns:
            if isbn in self._isbn:
                return self._isbn[isbn]
        return None

    async def match_title_author(self, title: str, author: str | None) -> str | None:
        return self._title.get(title)

    async def link_match(self, seed_id: str, record_id: str, via: CanonMatchVia) -> None:
        self.links.append((seed_id, record_id, via))
        self._unmatched.pop(seed_id, None)


def _row(
    seed_id: str,
    *,
    title: str = "T",
    author: str | None = None,
    isbns: tuple[str, ...] = (),
) -> CanonSeedRow:
    return CanonSeedRow(id=seed_id, title=title, author=author, isbn13=isbns)


async def test_isbn_match_takes_precedence() -> None:
    repo = _FakeRepo(
        [_row("s1", title="Pedro Páramo", isbns=("9788437604947",))],
        isbn_index={"9788437604947": "rec-isbn"},
        title_index={"Pedro Páramo": "rec-title"},
    )
    stats = await MatchCanonSeed(repository=repo).execute()
    assert stats.matched_isbn == 1
    assert stats.matched_title_author == 0
    assert repo.links == [("s1", "rec-isbn", CanonMatchVia.ISBN)]


async def test_title_author_fallback_when_no_isbn_hit() -> None:
    repo = _FakeRepo(
        [_row("s1", title="Rayuela", isbns=("0000000000000",))],
        title_index={"Rayuela": "rec-title"},
    )
    stats = await MatchCanonSeed(repository=repo).execute()
    assert stats.matched_title_author == 1
    assert repo.links == [("s1", "rec-title", CanonMatchVia.TITLE_AUTHOR)]


async def test_unmatched_row_is_left_unlinked() -> None:
    repo = _FakeRepo([_row("s1", title="Unheld classic")])
    stats = await MatchCanonSeed(repository=repo).execute()
    assert stats.unmatched == 1
    assert stats.matched == 0
    assert repo.links == []


async def test_mixed_pool_terminates_and_skips_unmatchable() -> None:
    # Half match by title, half never match — the sweep must finish (not loop on
    # the un-matchable rows) and scan every row exactly once.
    rows = [_row(f"s{i}", title=f"T{i}") for i in range(6)]
    repo = _FakeRepo(rows, title_index={f"T{i}": f"rec{i}" for i in range(0, 6, 2)})
    stats = await MatchCanonSeed(repository=repo, batch_size=2).execute()
    assert stats.scanned == 6
    assert stats.matched_title_author == 3
    assert stats.unmatched == 3
    assert len(repo.links) == 3


async def test_max_rows_bounds_the_sweep() -> None:
    rows = [_row(f"s{i}", title=f"T{i}") for i in range(10)]
    repo = _FakeRepo(rows, title_index={f"T{i}": f"rec{i}" for i in range(10)})
    stats = await MatchCanonSeed(repository=repo, batch_size=3).execute(max_rows=4)
    assert stats.scanned == 4
    assert stats.matched == 4
    assert len(repo.links) == 4
