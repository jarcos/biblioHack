"""Unit tests for the ImportShelf use case — match precedence + stats, with fakes."""

from __future__ import annotations

import pytest

from bibliohack.reading_history.application.use_cases.import_shelf import ImportShelf
from bibliohack.reading_history.domain.shelf import MatchVia, Shelf
from bibliohack.reading_history.infrastructure.goodreads.csv_parser import GoodreadsRow

pytestmark = pytest.mark.asyncio


class _FakeRepo:
    """Configurable fake: ISBN/title lookups via dicts, records upserts."""

    def __init__(
        self,
        *,
        isbn_hits: dict[str, str] | None = None,
        title_hits: dict[str, str] | None = None,
        existing: set[str] | None = None,
    ) -> None:
        self._isbn_hits = isbn_hits or {}
        self._title_hits = title_hits or {}
        self._existing = existing or set()
        self.upserts: list[tuple[str, str | None, MatchVia]] = []
        self.user_ids: set[str] = set()

    async def match_isbn13(self, isbn13: str) -> str | None:
        return self._isbn_hits.get(isbn13)

    async def match_title_author(self, title: str, author: str | None) -> str | None:
        return self._title_hits.get(title)

    async def upsert_entry(self, entry: object) -> bool:
        self.upserts.append(
            (entry.source_book_id, entry.matched_record_id, entry.matched_via)  # type: ignore[attr-defined]
        )
        self.user_ids.add(entry.user_id)  # type: ignore[attr-defined]
        return entry.source_book_id not in self._existing  # type: ignore[attr-defined]


def _row(
    book_id: str, *, title: str = "T", author: str | None = "A", isbn: str | None = None
) -> GoodreadsRow:
    return GoodreadsRow(
        source_book_id=book_id,
        title=title,
        author=author,
        isbn_13=isbn,
        shelf=Shelf.READ,
        rating=None,
        review=None,
        date_read=None,
        date_added=None,
    )


async def test_isbn_match_takes_precedence() -> None:
    repo = _FakeRepo(isbn_hits={"9788497934329": "rec-1"}, title_hits={"T": "rec-WRONG"})
    stats = await ImportShelf(repository=repo).execute(
        user_id="u-1", rows=[_row("1", isbn="9788497934329")]
    )
    assert stats.matched_isbn == 1
    assert stats.matched_title_author == 0
    assert repo.upserts == [("1", "rec-1", MatchVia.ISBN)]


async def test_title_author_fallback_when_isbn_misses() -> None:
    repo = _FakeRepo(isbn_hits={}, title_hits={"Nada": "rec-2"})
    stats = await ImportShelf(repository=repo).execute(
        [_row("2", title="Nada", isbn="9999999999999")], user_id="u-1"
    )
    assert stats.matched_title_author == 1
    assert stats.matched_isbn == 0
    assert repo.upserts[0] == ("2", "rec-2", MatchVia.TITLE_AUTHOR)


async def test_unmatched_when_no_isbn_and_no_title_hit() -> None:
    repo = _FakeRepo()
    stats = await ImportShelf(repository=repo).execute(
        user_id="u-1", rows=[_row("3", title="Obscure")]
    )
    assert stats.unmatched == 1
    assert stats.matched == 0
    assert repo.upserts[0] == ("3", None, MatchVia.NONE)


async def test_rows_without_isbn_skip_the_isbn_lookup() -> None:
    repo = _FakeRepo(title_hits={"T": "rec-9"})
    stats = await ImportShelf(repository=repo).execute(user_id="u-1", rows=[_row("4", isbn=None)])
    # No ISBN → straight to title match.
    assert stats.matched_title_author == 1


async def test_stats_aggregate_and_insert_vs_update() -> None:
    repo = _FakeRepo(
        isbn_hits={"9788497934329": "rec-1"},
        title_hits={"Nada": "rec-2"},
        existing={"updated-one"},
    )
    rows = [
        _row("new-isbn", isbn="9788497934329"),
        _row("updated-one", title="Nada"),
        _row("miss", title="Nope"),
    ]
    stats = await ImportShelf(repository=repo).execute(rows, user_id="u-1")
    assert stats.total == 3
    assert repo.user_ids == {"u-1"}  # every entry stamped with the importing user
    assert stats.matched_isbn == 1
    assert stats.matched_title_author == 1
    assert stats.unmatched == 1
    assert stats.inserted == 2  # new-isbn + miss
    assert stats.updated == 1  # updated-one
