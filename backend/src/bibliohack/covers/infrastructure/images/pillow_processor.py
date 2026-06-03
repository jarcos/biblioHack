"""Pillow ImageProcessor — normalise to WebP + content address (§7.5.4)."""

from __future__ import annotations

import hashlib
from io import BytesIO

from bibliohack.covers.application.ports import ProcessedImage


class PillowImageProcessor:
    """Decode arbitrary image bytes, downscale to a max edge, re-encode WebP.

    v1 produces a single canonical size; the three `srcset` derivatives
    (thumb / medium / large, §7.5.6) are a follow-up. `sha256` is taken over
    the encoded WebP bytes — the content address used by the CoverStore.
    """

    def __init__(self, *, max_edge: int = 600, quality: int = 82) -> None:
        self._max_edge = max_edge
        self._quality = quality

    def process(self, raw: bytes) -> ProcessedImage:
        # Lazy import — Pillow lives in the [covers] extra.
        from PIL import Image  # type: ignore[import-not-found,unused-ignore]

        with Image.open(BytesIO(raw)) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((self._max_edge, self._max_edge))  # preserves aspect ratio
            buffer = BytesIO()
            rgb.save(buffer, format="WEBP", quality=self._quality, method=6)
            webp = buffer.getvalue()
            width, height = rgb.size

        return ProcessedImage(
            webp=webp,
            sha256=hashlib.sha256(webp).hexdigest(),
            width=width,
            height=height,
        )
