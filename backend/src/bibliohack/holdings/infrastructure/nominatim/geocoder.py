"""OpenStreetMap Nominatim geocoder — branch town-centroid lookup (Libraries L0).

Off-OPAC: hits ``nominatim.openstreetmap.org/search`` to turn a branch's
municipality + province into a lat/lng. Users pick the *nearest town's* library,
so a town centroid is precise enough — we don't need a per-building address.

Nominatim's usage policy is strict and we honour it: **at most 1 request/second**
(the use case paces calls), a descriptive ``User-Agent`` with contact info (a 403
otherwise), and ``countrycodes=es`` + a structured query to keep results precise.

The JSON→coordinate mapping is a pure function (``parse_latlng``) so it's
unit-testable without the network; the client only adds transport. A hit returns
``(lat, lng)``; a miss or any transport/non-200 error returns ``None`` so the
caller leaves the branch ungeocoded and retries on a later run.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger(__name__)

_SEARCH_URL = "https://nominatim.openstreetmap.org/search"


def parse_latlng(payload: Sequence[Any]) -> tuple[float, float] | None:
    """Extract (lat, lng) from a Nominatim search response, or None if empty."""
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    if not isinstance(first, dict):
        return None
    raw_lat, raw_lng = first.get("lat"), first.get("lon")
    if raw_lat is None or raw_lng is None:
        return None
    try:
        return (float(raw_lat), float(raw_lng))
    except (TypeError, ValueError):
        return None


class NominatimGeocoder:
    """Resolve a municipality (+ optional province) to a lat/lng centroid."""

    def __init__(self, *, user_agent: str, timeout_seconds: float = 15.0) -> None:
        self._user_agent = user_agent
        self._timeout = timeout_seconds

    async def geocode(
        self, *, municipality: str, province: str | None = None
    ) -> tuple[float, float] | None:
        """Return (lat, lng) for the town, or None on miss/error."""
        import httpx  # type: ignore[import-not-found,unused-ignore]

        # Structured query: city + state, restricted to Spain, single best hit.
        params: dict[str, str] = {
            "city": municipality,
            "country": "España",
            "countrycodes": "es",
            "format": "jsonv2",
            "limit": "1",
        }
        if province:
            params["state"] = province
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                response = await client.get(
                    _SEARCH_URL,
                    params=params,
                    headers={"User-Agent": self._user_agent},
                )
        except httpx.HTTPError as exc:
            log.warning("nominatim.error municipality=%s error=%s", municipality, exc)
            return None

        if response.status_code != 200:
            log.warning(
                "nominatim.status municipality=%s status=%d", municipality, response.status_code
            )
            return None
        return parse_latlng(response.json())
