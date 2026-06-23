"""Unit tests for the RematchShelf use case — link precedence, stats, bounding."""

from __future__ import annotations

import pytest

from bibliohack.reading_history.application.ports import UnmatchedShelfEntry
from bibliohack.reading_history.application.use_cases.rematch_shelf import RematchShelf
from bibliohack.reading_history.domain.shelf import MatchVia

pytestmark = pytest.mark.asyncio


class _FakeRepo:
    """Fake ShelfRepository: serves unmatched entries, resolves via dicts, records links.

    `iter_unmatched` reflects linking: once an entry id is linked it stops being
    returned, so the use case's batch loop terminates exactly as it would against
    Postgres (where a set `matched_record_id` drops the row from the query).
    """

    def __init__(
        self,
        entries: list[UnmatchedShelfEntry],
        *,
        isbn_hits: dict[str, str] | None = None,
        title_hits: dict[str, str] | None = None,
    ) -> None:
        self._entries = list(entries)
        self._isbn_hits = isbn_hits or {}
        self._title_hits = title_hits or {}
        self._linked: set[str] = set()
        self.links: list[tuple[str, str, MatchVia]] = []

    async def match_isbn13(self, isbn13: str) -> str | None:
        return self._isbn_hits.get(isbn13)

    async def match_title_author(self, title: str, author: str | None) -> str | None:
        return self._title_hits.get(title)

    async def link_match(self, entry_id: str, record_id: str, via: MatchVia) -> None:
        self._linked.add(entry_id)
        self.links.append((entry_id, record_id, via))

    async def iter_unmatched(self, *, limit: int) -> list[UnmatchedShelfEntry]:
        pending = [e for e in self._entries if e.id not in self._linked]
        return pending[:limit]

    # Unused by RematchShelf but part of the protocol.
    async def upsert_entry(self, entry: object) -> bool:  # pragma: no cover
        raise NotImplementedError


def _entry(
    entry_id: str, *, title: str = "T", author: str | None = "A", isbn: str | None = None
) -> UnmatchedShelfEntry:
    return UnmatchedShelfEntry(id=entry_id, title=title, author=author, isbn_13=isbn)


async def test_isbn_link_takes_precedence() -> None:
    repo = _FakeRepo(
        [_entry("e1", isbn="9788497934329")],
        isbn_hits={"9788497934329": "rec-1"},
        title_hits={"T": "rec-WRONG"},
    )
    stats = await RematchShelf(repository=repo).execute()
    assert stats.linked_isbn == 1
    assert stats.linked_title_author == 0
    assert repo.links == [("e1", "rec-1", MatchVia.ISBN)]


async def test_title_author_fallback_when_isbn_misses() -> None:
    repo = _FakeRepo(
        [_entry("e2", title="Nada", isbn="9999999999999")],
        title_hits={"Nada": "rec-2"},
    )
    stats = await RematchShelf(repository=repo).execute()
    assert stats.linked_title_author == 1
    assert repo.links[0] == ("e2", "rec-2", MatchVia.TITLE_AUTHOR)


async def test_still_unmatched_is_left_untouched() -> None:
    repo = _FakeRepo([_entry("e3", title="Obscure")])
    stats = await RematchShelf(repository=repo).execute()
    assert stats.scanned == 1
    assert stats.linked == 0
    assert repo.links == []


async def test_entry_without_isbn_skips_isbn_lookup() -> None:
    repo = _FakeRepo([_entry("e4", isbn=None)], title_hits={"T": "rec-9"})
    stats = await RematchShelf(repository=repo).execute()
    assert stats.linked_title_author == 1


async def test_loop_terminates_and_aggregates_with_small_batches() -> None:
    # Mixed batch, batch_size 1 → exercises multi-iteration loop + termination
    # once the remaining head is unresolvable.
    repo = _FakeRepo(
        [
            _entry("hit-isbn", isbn="9788497934329"),
            _entry("hit-title", title="Nada"),
            _entry("miss", title="Nope"),
        ],
        isbn_hits={"9788497934329": "rec-1"},
        title_hits={"Nada": "rec-2"},
    )
    stats = await RematchShelf(repository=repo, batch_size=1).execute()
    assert stats.linked_isbn == 1
    assert stats.linked_title_author == 1
    assert {entry_id for entry_id, _, _ in repo.links} == {"hit-isbn", "hit-title"}


async def test_max_rows_bounds_the_scan() -> None:
    repo = _FakeRepo(
        [_entry(f"e{i}", title="Nada") for i in range(5)],
        title_hits={"Nada": "rec-2"},
    )
    stats = await RematchShelf(repository=repo, batch_size=10).execute(max_rows=2)
    assert stats.scanned == 2
    assert stats.linked == 2
