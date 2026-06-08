"""Content-addressed filesystem CoverStore (§7.5.5).

Dev / single-host store. Blobs live at ``{root}/{sha[:2]}/{sha}.webp`` — the
two-char prefix fans the tree out so directories stay small. Immutable: a
``put`` for an already-present sha is a no-op. A MinIO/S3 CoverStore is a
drop-in behind the same `CoverStore` port (slice 2 / prod).
"""

from __future__ import annotations

from pathlib import Path


class FilesystemCoverStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).expanduser()

    def _path(self, sha256: str) -> Path:
        return self._root / sha256[:2] / f"{sha256}.webp"

    async def exists(self, sha256: str) -> bool:
        return self._path(sha256).is_file()

    async def get(self, sha256: str) -> bytes | None:
        path = self._path(sha256)
        if not path.is_file():
            return None
        return path.read_bytes()

    async def put(self, sha256: str, data: bytes) -> None:
        path = self._path(sha256)
        if path.is_file():  # immutable — content address already stored
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
