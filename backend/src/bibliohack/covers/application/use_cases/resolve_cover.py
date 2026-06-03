"""ResolveCover — walk the provider chain, store the first hit, record metadata.

The heart of cover resolution (§7.5.4), kept off the OPAC path. Tries each
provider in order; the first that returns bytes is normalised to WebP,
stored content-addressed (dedup is automatic), and recorded as RESOLVED.
If no provider has it, the cover is recorded NOFOUND so the frontend shows a
placeholder and we don't re-resolve on every view. A provider or processing
error skips that source rather than failing the whole resolution.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bibliohack.covers.domain.cover import Cover, CoverSource, CoverStatus

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from bibliohack.covers.application.ports import (
        CoverProvider,
        CoverRepository,
        CoverStore,
        ImageProcessor,
    )

log = logging.getLogger(__name__)


class ResolveCover:
    """Use case: resolve one ISBN's cover through the provider chain."""

    def __init__(
        self,
        *,
        providers: Sequence[CoverProvider],
        processor: ImageProcessor,
        store: CoverStore,
        repository: CoverRepository,
    ) -> None:
        self._providers = providers
        self._processor = processor
        self._store = store
        self._repo = repository

    async def execute(self, isbn: str, *, record_id: UUID | None = None) -> Cover:
        for provider in self._providers:
            # One bad source must not abort the whole chain.
            try:
                fetched = await provider.fetch(isbn)
            except Exception:
                log.warning(
                    "covers.provider.error provider=%s isbn=%s", type(provider).__name__, isbn
                )
                continue
            if fetched is None:
                continue
            # A corrupt/odd image just skips this source.
            try:
                processed = self._processor.process(fetched.data)
            except Exception:
                log.warning("covers.process.error isbn=%s source=%s", isbn, fetched.source)
                continue

            if not await self._store.exists(processed.sha256):
                await self._store.put(processed.sha256, processed.webp)

            cover = Cover(
                isbn_13=isbn,
                status=CoverStatus.RESOLVED,
                source=fetched.source,
                record_id=record_id,
                license=fetched.license,
                sha256=processed.sha256,
                width=processed.width,
                height=processed.height,
                fetched_at=datetime.now(tz=UTC),
            )
            await self._repo.upsert(cover)
            return cover

        # No source had it → placeholder state.
        cover = Cover(
            isbn_13=isbn,
            status=CoverStatus.NOFOUND,
            source=CoverSource.PLACEHOLDER,
            record_id=record_id,
            fetched_at=datetime.now(tz=UTC),
        )
        await self._repo.upsert(cover)
        return cover
