"""Unit test for PillowImageProcessor — skipped when Pillow isn't installed.

Pillow lives in the [covers] extra, so this skips on a core/dev env that
doesn't have it; CI with the extra exercises the real WebP encode.
"""

from __future__ import annotations

from io import BytesIO

import pytest

pytest.importorskip("PIL")


def test_process_downscales_and_encodes_webp() -> None:
    from PIL import Image

    from bibliohack.covers.infrastructure.images.pillow_processor import PillowImageProcessor

    src = Image.new("RGB", (1000, 1500), (200, 30, 30))
    buffer = BytesIO()
    src.save(buffer, format="PNG")

    processed = PillowImageProcessor(max_edge=600).process(buffer.getvalue())

    assert processed.webp[:4] == b"RIFF"  # WebP RIFF container magic
    assert len(processed.sha256) == 64
    # 1000x1500 capped at max-edge 600 preserves aspect -> 400x600.
    assert (processed.width, processed.height) == (400, 600)
