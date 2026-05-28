"""AbsysNET HTML parser.

Turns the rendered OPAC HTML (post-JS-execution) into structured Python data.

The OPAC embeds MARC-21-flavored fields as `<span class="js-T<number>">` tags,
so we get the structured catalog metadata for free without needing to chase
visual layout. This is also more drift-resistant than DOM-position-based
parsing: as long as upstream keeps the `js-T*` convention, our parser works
even if they re-skin the rest of the page.

Reference (MARC 21 bibliographic fields we use):
- T1XX : main entry (T100 = personal author, T110 = corporate, T111 = meeting)
- T245 : title statement
- T260 : imprint (publisher, place, year)
- T080 : UDC classification
- T008 : control field (fixed-length: pub_year, language, country …)

Copies are in `<div class="copias_data js-copias_data">` blocks, one per branch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from selectolax.parser import HTMLParser

if TYPE_CHECKING:
    from bibliohack.catalog.domain.titn import Titn


# ───────────────────────────────────────────────────────────────
# DTOs
# ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ParsedRecord:
    """Bibliographic fields extracted from a single record page.

    Optional fields are `None` rather than empty string so the persistence
    layer can tell "not present" from "explicitly blank".
    """

    titn: int
    title: str
    authors: tuple[str, ...] = ()
    publisher: str | None = None
    classification: str | None = None  # UDC / T080
    document_type: str | None = None
    language: str | None = None
    pub_year: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedCopy:
    """A single copy / ejemplar held by some branch."""

    branch_code: str
    branch_name: str
    # Detailed per-copy fields (signature, barcode) are not exposed in the
    # main record page — they're loaded into the accordion on demand. We
    # capture what's available now; extend in a later commit when we drive
    # the accordion open.


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Everything the parser extracted from one record page."""

    record: ParsedRecord
    copies: tuple[ParsedCopy, ...] = field(default_factory=tuple)


# ───────────────────────────────────────────────────────────────
# Errors
# ───────────────────────────────────────────────────────────────


class ParseError(Exception):
    """The HTML did not contain a record we could parse."""


# ───────────────────────────────────────────────────────────────
# Public API
# ───────────────────────────────────────────────────────────────


def parse_record_html(html: str, *, expected_titn: Titn | None = None) -> ParseResult:
    """Parse a rendered AbsysNET record page.

    `expected_titn` is optional — if provided, we assert the page actually
    contains that TITN as a defence against URL/redirect mismatches.
    """
    if not html or not html.strip():
        msg = "Cannot parse empty HTML"
        raise ParseError(msg)

    tree = HTMLParser(html)

    # ── TITN ──────────────────────────────────────────────────
    titn_str = _first_js_field(tree, "TITN")
    if not titn_str:
        msg = "No TITN field in HTML — page is not a record view"
        raise ParseError(msg)
    try:
        titn = int(titn_str)
    except ValueError as e:
        msg = f"TITN field is not an integer: {titn_str!r}"
        raise ParseError(msg) from e

    if expected_titn is not None and titn != int(expected_titn):
        msg = f"TITN mismatch: page says {titn}, expected {int(expected_titn)}"
        raise ParseError(msg)

    # ── Title (T245) ──────────────────────────────────────────
    title = _first_js_field(tree, "T245")
    if not title:
        # Some records have title only in a header element, not in the marc
        # span. Fall back to the visible <span class="doc_title">.
        node = tree.css_first(".doc_title")
        if node is not None and node.text(strip=True):
            title = node.text(strip=True)
    if not title:
        msg = "No title (T245 / .doc_title) in HTML"
        raise ParseError(msg)

    # ── Authors (T1XX) ────────────────────────────────────────
    authors = tuple(_all_js_fields(tree, "T1XX"))

    # ── Publisher (T260) ──────────────────────────────────────
    publisher = _first_js_field(tree, "T260") or _first_js_field(tree, "T260ab")
    # T260 sometimes contains "Place : Publisher, Year". We try to keep just
    # the publisher portion — the simplest heuristic is "drop everything
    # before the last colon, then drop the trailing year".
    if publisher and ":" in publisher:
        publisher = publisher.rsplit(":", 1)[-1].strip(" ,.")
    if publisher:
        publisher = re.sub(r",?\s*\d{4}\s*$", "", publisher).strip(" ,.") or publisher

    # ── Classification (T080) ─────────────────────────────────
    classification = _first_js_field(tree, "T080")

    # ── Document type ─────────────────────────────────────────
    # Surfaced visually under the title as "Monografías", "Audiolibro", etc.
    # Look for `.tipodoc` or `.h-hdd` near `Tipo de documento`.
    document_type = _extract_document_type(tree)

    # ── Language (T008 / js-LENG) ─────────────────────────────
    language = _first_js_field(tree, "LENG") or None

    # ── Publication year (js-FEPU / T260) ─────────────────────
    pub_year = _extract_pub_year(tree)

    record = ParsedRecord(
        titn=titn,
        title=title.strip(),
        authors=tuple(a.strip() for a in authors if a.strip()),
        publisher=publisher or None,
        classification=classification or None,
        document_type=document_type,
        language=language,
        pub_year=pub_year,
    )

    # ── Copies ────────────────────────────────────────────────
    copies = tuple(_parse_copies(tree))

    return ParseResult(record=record, copies=copies)


def looks_like_not_found(html: str) -> bool:
    """Cheap check for the OPAC's 'no results' state.

    Mirrors the markers in the gateway — keep in sync. Useful for callers
    that have HTML in hand and want to short-circuit before calling the
    full parser.
    """
    if not html:
        return False
    lowered = html.lower()
    return any(
        marker in lowered
        for marker in (
            "no recupera resultados",
            "(0 docs.)",
            "no se ha encontrado",
            "registro no encontrado",
        )
    )


# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────


def _first_js_field(tree: HTMLParser, name: str) -> str | None:
    """First non-empty text content of any element carrying class `js-<name>`."""
    for node in tree.css(f".js-{name}"):
        text = node.text(strip=True)
        if text:
            return text
    return None


def _all_js_fields(tree: HTMLParser, name: str) -> list[str]:
    """All non-empty text contents of elements carrying class `js-<name>`."""
    out: list[str] = []
    seen: set[str] = set()
    for node in tree.css(f".js-{name}"):
        text = node.text(strip=True)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _extract_document_type(tree: HTMLParser) -> str | None:
    """The OPAC shows the document type as a small label near the title.

    Common values: 'Monografías', 'Audiolibro', 'Revistas', 'Publicación
    seriada', etc. We look for the `.tipodoc` or `.h-tipodoc` selector;
    fall back to scanning visible 'Tipo de documento' labels.
    """
    for sel in (".tipodoc", ".h-tipodoc", "[data-tipodoc]"):
        node = tree.css_first(sel)
        if node is not None:
            text = node.text(strip=True)
            if text:
                return text
    return None


def _extract_pub_year(tree: HTMLParser) -> int | None:
    """Pub year from `js-FEPU` if present; otherwise from a 4-digit run in T260."""
    fepu = _first_js_field(tree, "FEPU")
    if fepu and fepu.isdigit() and len(fepu) >= 4:
        return int(fepu[:4])
    t260 = _first_js_field(tree, "T260")
    if t260:
        m = re.search(r"\b(1[4-9]\d{2}|20\d{2}|21\d{2})\b", t260)
        if m:
            return int(m.group(1))
    return None


def _parse_copies(tree: HTMLParser) -> list[ParsedCopy]:
    """One ParsedCopy per `<div class="copias_data js-copias_data">` block.

    Each block carries an `id="copias_bib<CODE>"` and a `<span>Biblioteca:</span>
    <span>NAME</span>` pair.
    """
    out: list[ParsedCopy] = []
    seen_codes: set[str] = set()

    for block in tree.css(".copias_data.js-copias_data"):
        # Branch code lives in any descendant with id="copias_bib<CODE>".
        code = _branch_code_from_block(block.html or "")
        if not code or code in seen_codes:
            continue
        # Branch name: first <span> after <span class="h-hdd">Biblioteca:</span>.
        name = _branch_name_from_block(block.html or "")
        if not name:
            continue
        seen_codes.add(code)
        out.append(ParsedCopy(branch_code=code, branch_name=name))

    return out


_BRANCH_ID_RE = re.compile(r'id="copias_bib([A-Za-z0-9]+)"')
_BRANCH_NAME_RE = re.compile(
    r'<span class="h-hdd">Biblioteca:\s*</span>\s*<span[^>]*>([^<]+)</span>',
    re.IGNORECASE,
)


def _branch_code_from_block(block_html: str) -> str | None:
    m = _BRANCH_ID_RE.search(block_html)
    if m is None:
        return None
    captured: str = m.group(1)
    return captured


def _branch_name_from_block(block_html: str) -> str | None:
    m = _BRANCH_NAME_RE.search(block_html)
    if m is None:
        return None
    captured: str = m.group(1)
    return captured.strip()
