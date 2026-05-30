"""One-off diagnostic for the title mojibake bug. Fetches a known-accented
record live and reports the charset story at each stage. Safe: one polite fetch.

Run from backend/ venv:
    .venv/bin/python ../scripts/diag_encoding.py
"""

from __future__ import annotations

import re

URL = "https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?TITN=11"


def show(label: str, s: str) -> None:
    print(f"--- {label} ---")
    print(repr(s))
    print()


def main() -> None:
    from scrapling.fetchers import StealthyFetcher

    page = StealthyFetcher.fetch(
        URL, headless=True, network_idle=True,
        extra_headers={"User-Agent": "bibliohack/0.1 (+diag)"},
    )

    print("status:", getattr(page, "status", "?"))
    # What attributes does the page expose?
    attrs = [a for a in dir(page) if not a.startswith("_")]
    print("page attrs:", [a for a in attrs if a in
          ("html_content", "body", "encoding", "text", "content", "url", "status")])
    print()

    html = str(getattr(page, "html_content", "") or getattr(page, "body", ""))

    # 1. declared charset
    m = re.search(r'charset=["\']?([\w-]+)', html[:4000], re.I)
    print("declared meta charset:", m.group(1) if m else "NONE FOUND")
    print()

    # 1b. is the guard satisfied and does whole-doc round-trip work?
    print("guard matches latin-1 decl:", bool(re.search(
        r'charset=["\']?\s*(?:iso-8859-1|latin-?1)', html[:4096], re.I)))
    over = [c for c in html if ord(c) > 0xFF]
    print("chars > U+00FF in full doc:", len(over),
          "samples:", [hex(ord(c)) for c in over[:8]])
    try:
        html.encode("latin-1")
        print("whole-doc .encode('latin-1'): OK")
    except UnicodeEncodeError as e:
        print("whole-doc .encode('latin-1'): RAISES ->", e)
    print()

    # 1c. apply the REAL gateway repair and re-extract the title
    from bibliohack.catalog.infrastructure.absysnet.gateway import _repair_charset
    from selectolax.parser import HTMLParser as _HP
    repaired_doc = _repair_charset(html)
    _t = _HP(repaired_doc).css_first(".js-T245")
    print("AFTER _repair_charset, .js-T245:",
          repr(_t.text(strip=True)[:80]) if _t else "(none)")
    print("repl chars introduced:", repaired_doc.count("�"))
    print()

    # 2. find a window around an accented author/title token
    for needle in ("Jes", "Garc", "Gxmez", "mez", "T245", "T1XX"):
        i = html.find(needle)
        if i != -1:
            show(f"window @ {needle!r}", html[i : i + 40])
            break

    # 3. pull the js-T245 / js-T1XX text the parser actually reads
    from selectolax.parser import HTMLParser
    tree = HTMLParser(html)
    for cls in ("js-T245", "js-T1XX", "js-T100"):
        node = tree.css_first(f".{cls}")
        if node is not None:
            txt = node.text(strip=True)
            show(f".{cls} text (parser sees)", txt[:80])
            # 4. attempt the classic double-encode reversal
            try:
                fixed = txt.encode("latin-1").decode("utf-8")
                show(f".{cls} latin1->utf8 reversal", fixed[:80])
            except (UnicodeEncodeError, UnicodeDecodeError) as e:
                print(f"  reversal failed for .{cls}: {e}\n")


if __name__ == "__main__":
    main()
