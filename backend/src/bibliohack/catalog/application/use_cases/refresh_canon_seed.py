"""RefreshCanonSeed — pull the canon list from a source and upsert it (C0).

Off the OPAC path entirely (see ``docs/design/canon-import.md`` → "Ops"). It
streams clean :class:`CanonSeedWork` objects from a :class:`CanonSeedSource`
(Wikidata today) and upserts them in batches, keyed by ``(source, source_ref)``
so re-running is idempotent: a monthly refresh updates works in place and adds
newly-notable ones rather than duplicating. Pure application logic — the SPARQL
transport and the SQL live behind the source and repository ports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bibliohack.catalog.application.ports import (
        CanonSeedRepository,
        CanonSeedSource,
    )
    from bibliohack.catalog.domain.canon import CanonSeedWork

DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class RefreshSeedStats:
    """Outcome of a refresh run."""

    fetched: int = 0
    inserted: int = 0
    updated: int = 0

    @property
    def upserted(self) -> int:
        return self.inserted + self.updated


class RefreshCanonSeed:
    """Stream works from a source and upsert them into the seed."""

    def __init__(
        self,
        *,
        source: CanonSeedSource,
        repository: CanonSeedRepository,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._source = source
        self._repo = repository
        self._batch_size = max(1, batch_size)

    async def execute(self, *, max_works: int | None = None) -> RefreshSeedStats:
        """Fetch up to `max_works` (or all) and upsert in batches."""
        fetched = inserted = updated = 0
        batch: list[CanonSeedWork] = []

        async for work in self._source.fetch_works(max_works=max_works):
            fetched += 1
            batch.append(work)
            if len(batch) >= self._batch_size:
                result = await self._repo.upsert_works(batch)
                inserted += result.inserted
                updated += result.updated
                batch.clear()

        if batch:
            result = await self._repo.upsert_works(batch)
            inserted += result.inserted
            updated += result.updated

        return RefreshSeedStats(fetched=fetched, inserted=inserted, updated=updated)
