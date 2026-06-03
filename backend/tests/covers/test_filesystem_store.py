"""Unit tests for the content-addressed FilesystemCoverStore."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bibliohack.covers.infrastructure.store.filesystem import FilesystemCoverStore

if TYPE_CHECKING:
    from pathlib import Path


async def test_put_then_exists_and_fans_out_by_prefix(tmp_path: Path) -> None:
    store = FilesystemCoverStore(tmp_path)
    sha = "deadbeef" * 8  # 64 hex chars

    assert await store.exists(sha) is False
    await store.put(sha, b"webp-bytes")
    assert await store.exists(sha) is True
    assert (tmp_path / sha[:2] / f"{sha}.webp").read_bytes() == b"webp-bytes"


async def test_put_is_idempotent_immutable(tmp_path: Path) -> None:
    store = FilesystemCoverStore(tmp_path)
    sha = "ab" + "0" * 62

    await store.put(sha, b"first")
    await store.put(sha, b"second")  # same content address → must not overwrite

    assert (tmp_path / sha[:2] / f"{sha}.webp").read_bytes() == b"first"
