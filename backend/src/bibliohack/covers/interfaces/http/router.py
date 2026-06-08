"""Serve cover images from the content-addressed CoverStore.

`GET /catalog/covers/{sha256}.webp` — streams the WebP bytes for a stored
cover. URLs are content-addressed (immutable), so we set a one-year immutable
`Cache-Control`; Cloudflare can then edge-cache each cover and the NAS serves
it essentially once. Mounted under `/catalog` so it rides the existing tunnel
route to the api with no extra ingress config.

This is read-only: the resolver (crawler plane) writes covers; the api only
reads, via a shared volume (or a future MinIO store behind the same port).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Response, status

from bibliohack.covers.infrastructure.store.filesystem import FilesystemCoverStore
from bibliohack.shared.infrastructure.settings import get_settings

router = APIRouter(prefix="/catalog/covers", tags=["covers"])

# A cover id is exactly a hex sha-256. Validating it also blocks any path
# traversal before the value ever reaches the store.
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


@router.get(
    "/{sha256}.webp",
    responses={404: {"description": "No cover stored under this content address."}},
)
async def get_cover(sha256: str) -> Response:
    if not _SHA256.match(sha256):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not a cover id")
    store = FilesystemCoverStore(get_settings().covers_store_path)
    data = await store.get(sha256)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cover not found")
    return Response(
        content=data,
        media_type="image/webp",
        headers={"Cache-Control": _IMMUTABLE_CACHE},
    )
