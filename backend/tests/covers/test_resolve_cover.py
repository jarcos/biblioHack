"""Unit tests for the ResolveCover use case (all ports stubbed)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bibliohack.covers.application.ports import FetchedImage, ProcessedImage
from bibliohack.covers.application.use_cases.resolve_cover import ResolveCover
from bibliohack.covers.domain.cover import Cover, CoverSource, CoverStatus

if TYPE_CHECKING:
    from bibliohack.covers.application.ports import (
        CoverProvider,
        CoverRepository,
        CoverStore,
        ImageProcessor,
    )


class _StubProvider:
    def __init__(self, image: FetchedImage | None) -> None:
        self._image = image
        self.calls: list[str] = []

    async def fetch(self, isbn: str) -> FetchedImage | None:
        self.calls.append(isbn)
        return self._image


class _BoomProvider:
    async def fetch(self, isbn: str) -> FetchedImage | None:
        msg = "network down"
        raise RuntimeError(msg)


class _StubProcessor:
    def process(self, raw: bytes) -> ProcessedImage:
        return ProcessedImage(webp=b"WEBP" + raw, sha256="abc123", width=400, height=600)


class _FakeStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def exists(self, sha256: str) -> bool:
        return sha256 in self.blobs

    async def put(self, sha256: str, data: bytes) -> None:
        self.blobs[sha256] = data


class _FakeRepo:
    def __init__(self) -> None:
        self.saved: list[Cover] = []

    async def get_by_isbn(self, isbn: str) -> Cover | None:
        return None

    async def upsert(self, cover: Cover) -> None:
        self.saved.append(cover)

    async def isbns_needing_cover(self, *, limit: int) -> list[str]:
        return []


def _use_case(
    providers: list[object],
    store: _FakeStore | None = None,
    repo: _FakeRepo | None = None,
) -> ResolveCover:
    return ResolveCover(
        providers=cast("list[CoverProvider]", providers),
        processor=cast("ImageProcessor", _StubProcessor()),
        store=cast("CoverStore", store or _FakeStore()),
        repository=cast("CoverRepository", repo or _FakeRepo()),
    )


async def test_resolves_from_first_provider_with_a_hit() -> None:
    store = _FakeStore()
    repo = _FakeRepo()
    provider = _StubProvider(
        FetchedImage(data=b"img", source=CoverSource.OPENLIBRARY, license="openlibrary")
    )

    cover = await _use_case([provider], store, repo).execute("9788433920416")

    assert cover.status is CoverStatus.RESOLVED
    assert cover.source is CoverSource.OPENLIBRARY
    assert cover.sha256 == "abc123"
    assert store.blobs == {"abc123": b"WEBPimg"}
    assert repo.saved[-1].is_resolved


async def test_records_nofound_when_no_provider_has_it() -> None:
    repo = _FakeRepo()
    cover = await _use_case([_StubProvider(None)], repo=repo).execute("9780000000000")
    assert cover.status is CoverStatus.NOFOUND
    assert cover.source is CoverSource.PLACEHOLDER
    assert not cover.is_resolved
    assert repo.saved[-1].status is CoverStatus.NOFOUND


async def test_skips_a_failing_provider_and_uses_the_next() -> None:
    good = _StubProvider(FetchedImage(data=b"x", source=CoverSource.OPENLIBRARY))
    cover = await _use_case([_BoomProvider(), good]).execute("9788433920416")
    assert cover.status is CoverStatus.RESOLVED
    assert good.calls == ["9788433920416"]


async def test_does_not_overwrite_an_existing_blob() -> None:
    store = _FakeStore()
    store.blobs["abc123"] = b"already-there"
    provider = _StubProvider(FetchedImage(data=b"img", source=CoverSource.OPENLIBRARY))

    await _use_case([provider], store).execute("9788433920416")

    assert store.blobs["abc123"] == b"already-there"  # immutable — not re-put
