"""RefreshCanonSeed (C0) — batching + idempotent upsert accounting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.catalog.application.ports import CanonUpsertResult
from bibliohack.catalog.application.use_cases.refresh_canon_seed import RefreshCanonSeed
from bibliohack.catalog.domain.canon import CanonSeedWork, CanonSource

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence


class _FakeSource:
    """Yields a fixed list of works, honouring max_works."""

    def __init__(self, works: list[CanonSeedWork]) -> None:
        self._works = works

    async def fetch_works(self, *, max_works: int | None = None) -> AsyncIterator[CanonSeedWork]:
        for i, work in enumerate(self._works):
            if max_works is not None and i >= max_works:
                return
            yield work


class _FakeRepo:
    """Records each upsert batch; treats already-seen QIDs as updates."""

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.batches: list[int] = []

    async def upsert_works(self, works: Sequence[CanonSeedWork]) -> CanonUpsertResult:
        self.batches.append(len(works))
        inserted = updated = 0
        for w in works:
            if w.source_ref in self.seen:
                updated += 1
            else:
                self.seen.add(w.source_ref)
                inserted += 1
        return CanonUpsertResult(inserted=inserted, updated=updated)


def _works(n: int) -> list[CanonSeedWork]:
    return [
        CanonSeedWork(source=CanonSource.WIKIDATA, source_ref=f"Q{i}", title=f"Work {i}")
        for i in range(n)
    ]


async def test_streams_and_batches_upserts() -> None:
    source = _FakeSource(_works(5))
    repo = _FakeRepo()
    stats = await RefreshCanonSeed(source=source, repository=repo, batch_size=2).execute()

    assert stats.fetched == 5
    assert stats.inserted == 5
    assert stats.updated == 0
    # 2 + 2 + 1 — the trailing partial batch is flushed.
    assert repo.batches == [2, 2, 1]


async def test_max_works_caps_fetch() -> None:
    source = _FakeSource(_works(10))
    repo = _FakeRepo()
    stats = await RefreshCanonSeed(source=source, repository=repo, batch_size=4).execute(
        max_works=3
    )
    assert stats.fetched == 3
    assert stats.inserted == 3


async def test_rerun_counts_as_updates_idempotent() -> None:
    repo = _FakeRepo()
    await RefreshCanonSeed(source=_FakeSource(_works(3)), repository=repo).execute()
    stats = await RefreshCanonSeed(source=_FakeSource(_works(3)), repository=repo).execute()
    assert stats.inserted == 0
    assert stats.updated == 3
