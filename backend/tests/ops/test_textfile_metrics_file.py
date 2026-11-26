"""TextfileMetricsFile: the file node-exporter's textfile collector reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bibliohack.ops.infrastructure.textfile import TextfileMetricsFile

if TYPE_CHECKING:
    from pathlib import Path


def test_reads_nothing_when_the_file_does_not_exist(tmp_path: Path) -> None:
    assert TextfileMetricsFile(tmp_path / "bibliohack.prom").read() is None


def test_writes_in_place_and_reads_back(tmp_path: Path) -> None:
    path = tmp_path / "bibliohack.prom"
    path.write_text("old content that is longer than the new one\n")
    metrics_file = TextfileMetricsFile(path)

    metrics_file.write("bibliohack_schema_drift 0\n")

    assert metrics_file.read() == "bibliohack_schema_drift 0\n"


def test_never_needs_to_create_files_in_the_directory(tmp_path: Path) -> None:
    # The NAS textfile directory belongs to another user: the crawler can write
    # the one file it was given, not create new ones (no temp file + rename).
    path = tmp_path / "bibliohack.prom"
    path.write_text("")
    tmp_path.chmod(0o555)
    try:
        TextfileMetricsFile(path).write("bibliohack_schema_drift 1\n")
    finally:
        tmp_path.chmod(0o755)

    assert path.read_text() == "bibliohack_schema_drift 1\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bibliohack.prom"]


def test_a_missing_file_is_an_error_not_a_silent_skip(tmp_path: Path) -> None:
    # In production the file is created once by hand with write permission
    # for the crawler; if it disappears the job must fail so the metrics go
    # stale and the meta-alert fires.
    (tmp_path / "ro").mkdir(mode=0o555)
    with pytest.raises(OSError, match=r"bibliohack\.prom"):
        TextfileMetricsFile(tmp_path / "ro" / "bibliohack.prom").write("x\n")
