"""Standalone Scrapling smoke test.

Bypasses our gateway entirely — just verifies Scrapling can talk to the
live OPAC. If THIS fails, the problem is upstream (Scrapling /
Camoufox / network), not our code.

Run with:  cd backend && uv run python ../scripts/scrapling_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback


async def main() -> int:
    print("=== Scrapling smoke test ===", flush=True)
    try:
        from scrapling.fetchers import StealthyFetcher  # type: ignore[import-not-found]
    except Exception:
        print("Failed to IMPORT StealthyFetcher:", flush=True)
        traceback.print_exc()
        return 1

    print(f"  StealthyFetcher: {StealthyFetcher!r}", flush=True)
    fetch_methods = [a for a in dir(StealthyFetcher) if "fetch" in a.lower()]
    print(f"  Fetch-related attrs: {fetch_methods}", flush=True)

    url = "https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?TITN=1"
    print(f"  Fetching: {url}", flush=True)

    try:
        page = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=30_000,
        )
    except Exception:
        print("Failed to FETCH:", flush=True)
        traceback.print_exc()
        return 2

    print("Fetched. Page attrs:", flush=True)
    print(f"  type:   {type(page).__name__}", flush=True)
    print(f"  status: {getattr(page, 'status', '<no attr>')}", flush=True)
    print(f"  url:    {getattr(page, 'url', '<no attr>')}", flush=True)
    body = getattr(page, "html_content", None) or getattr(page, "body", None) or ""
    body_str = str(body)
    print(f"  body length: {len(body_str)}", flush=True)
    if "0044 y medio" in body_str.lower():
        print("  ✓ title 'IBM y compañía Arantza' present in body", flush=True)
    else:
        print("  ✗ expected title NOT found in body", flush=True)
        print(f"  body preview: {body_str[:200]!r}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
