"""The node-exporter textfile the health metrics go to.

On the NAS the textfile directory (`/volume1/docker/db-backup/textfile`,
mounted at `/textfile`) belongs to another user; the crawler (uid 1000) is
given one pre-created file it may write, not the directory. So the file is
rewritten in place — no temp file and rename, which would need to create a
file there. A reader can catch it half-written for an instant; node-exporter
then skips it for one scrape, which no alert (all have a `for:`) notices.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class TextfileMetricsFile:
    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> str | None:
        try:
            return self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def write(self, content: str) -> None:
        with self._path.open("w", encoding="utf-8") as handle:
            handle.write(content)
