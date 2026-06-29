#!/usr/bin/env python3
"""Generate the human-readable docs/site/ HTML from canonical Markdown.

Single source of truth: the Markdown files listed in ``PAGES`` (design docs in
``docs/design/`` and site-only pages in ``docs/site/_src/``). The styled HTML
under ``docs/site/`` is a build artifact — never edit it by hand. Run via
``make docs``; CI regenerates and fails on any diff (see .github/workflows).

Deps: markdown, jinja2, pyyaml (declared in the ``docs`` dependency group).
"""

from __future__ import annotations

import pathlib
import shutil
import sys

import markdown
import yaml
from jinja2 import Template

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DESIGN = DOCS / "design"
SRC = DOCS / "site" / "_src"
SITE = DOCS / "site"
TEMPLATE = Template((ROOT / "tools" / "doc_template.html").read_text(encoding="utf-8"))

# (source_md, output_html, nav_label, wide) — order defines the nav crumbs.
PAGES: list[tuple[pathlib.Path, str, str, bool]] = [
    (SRC / "index.md", "index.html", "Overview", False),
    (DESIGN / "architecture.md", "architecture.html", "Architecture", False),
    (DESIGN / "identity-milestone.md", "identity-milestone.html", "Identity Milestone", False),
    (DESIGN / "relevance-and-libraries.md", "relevance-and-libraries.html", "Relevance & Libraries", False),
    (DESIGN / "canon-import.md", "canon-import.html", "Canon Import", False),
    (DESIGN / "demand-driven-shelf-fetcher.md", "demand-driven-shelf-fetcher.html", "Demand-driven Fetcher", False),
    (DESIGN / "m7-backlist-crawl.md", "m7-backlist-crawl.html", "M7 Backlist Crawl", False),
    (DESIGN / "library-aware-availability.md", "library-aware-availability.html", "Library-aware Availability", False),
    (SRC / "pending-and-ops.md", "pending-and-ops.html", "Pending & Operations", False),
    (SRC / "kanban.md", "kanban.html", "Kanban", True),
]

MD_EXTENSIONS = ["tables", "fenced_code", "attr_list", "sane_lists", "toc"]


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Split optional leading ``---`` YAML front matter from the body."""
    if text.startswith("---\n"):
        _, fm, body = text.split("---\n", 2)
        return (yaml.safe_load(fm) or {}), body
    return {}, text


def render_body(meta: dict, body: str) -> str:
    """Site-only pages carry raw HTML bodies; design docs are Markdown."""
    if meta.get("raw_html"):
        return body
    return markdown.markdown(body, extensions=MD_EXTENSIONS, output_format="html5")


def build() -> int:
    SITE.mkdir(parents=True, exist_ok=True)
    nav = [(label, out) for (_src, out, label, _wide) in PAGES]
    missing = [str(src) for src, *_ in PAGES if not src.exists()]
    if missing:
        print("ERROR: missing source files:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1

    for src, out, label, wide in PAGES:
        meta, body = parse_front_matter(src.read_text(encoding="utf-8"))
        page = TEMPLATE.render(
            title=meta.get("title", f"biblioHack — {label}"),
            h1=meta.get("h1", "📚 biblioHack"),
            tagline=meta.get("tagline", ""),
            body=render_body(meta, body),
            nav=nav,
            current=out,
            wide=wide,
        )
        (SITE / out).write_text(page, encoding="utf-8")
        print(f"  {src.relative_to(ROOT)} -> {(SITE / out).relative_to(ROOT)}")

    favicon = SRC / "favicon.svg"
    if favicon.exists():
        shutil.copyfile(favicon, SITE / "favicon.svg")
    print(f"Built {len(PAGES)} pages into {SITE.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
