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
- T6XX : subject access (T650 = topical term, T651 = geographic name,
         T655 = genre/form term). Folded together into `subjects`.
- T008 : control field (fixed-length: pub_year, language, country …)

Copies are in `<div class="copias_data js-copias_data">` blocks, one per branch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from selectolax.parser import HTMLParser

from bibliohack.catalog.domain.isbn import normalize_to_isbn13

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

    `record_type` / `bibliographic_level` are the two MARC leader positions
    used by the media-type filter to decide whether to persist this record
    (book vs. audiobook vs. magazine vs. video vs. ...). See
    `catalog/domain/media_filter.py` for the full code table.
    """

    titn: int
    title: str
    authors: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()  # MARC T650/T651/T655, deduped, in order
    isbns: tuple[str, ...] = ()  # MARC T020$a, normalized to ISBN-13, deduped
    publisher: str | None = None
    classification: str | None = None  # UDC / T080
    document_type: str | None = None
    language: str | None = None
    pub_year: int | None = None
    record_type: str | None = None  # MARC LDR/06 — single character, e.g. 'a'
    bibliographic_level: str | None = None  # MARC LDR/07 — single character, e.g. 'm'


@dataclass(frozen=True, slots=True)
class ParsedCopy:
    """A single copy / ejemplar held by some branch.

    M2 extends this with per-ejemplar data scraped from the inner
    accordion table:

    - `signature` — the physical call number (e.g. ``"N ARS roh"``).
    - `barcode`   — the local barcode used by the loan system.
    - `raw_status` — the OPAC's literal `data-disp` value
      (``"Disponible"``, ``"Prestado"``, ``"En inventario"``, ...).
      The availability bounded context maps this to its domain enum.

    All three are optional because some bibliotecas don't expose per-
    ejemplar rows (e.g. virtual / digital copies show only the
    biblioteca header). In that case we still emit a ParsedCopy so
    the holdings layer knows the record is present at that branch,
    just without ejemplar-level detail.
    """

    branch_code: str
    branch_name: str
    signature: str | None = None
    barcode: str | None = None
    raw_status: str | None = None


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Everything the parser extracted from one record page."""

    record: ParsedRecord
    copies: tuple[ParsedCopy, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SearchResultsPage:
    """One page of an AbsysNET DOSEARCH results list.

    `titns` are the records shown on this page (10 per page on the RBPA OPAC),
    extracted from the `js-TITN` spans. `next_url` is the (root-relative) href
    of the "Siguiente" control, or None on the last page. `total` is the
    reported result count ("N Registros") when present.
    """

    titns: tuple[int, ...]
    next_url: str | None = None
    total: int | None = None


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

    # ── Subjects (T650 topical / T651 geographic / T655 genre) ─
    # Folded into one ordered, deduped list. These feed subject facets,
    # the literary-form classifier, and (later, M3) the embedding text.
    subjects = tuple(_extract_subjects(tree))

    # ── ISBNs (T020 $a) ───────────────────────────────────────
    # AbsysNET renders the ISBN subfield $a as `js-T020a` (the `js-T020aq`
    # variant carries trailing qualifier junk, so target $a exactly).
    # Normalized to ISBN-13 — the form the covers context is keyed on.
    isbns = tuple(_extract_isbns(tree))

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

    # ── MARC leader positions 06 (record type) and 07 (bibliographic level)
    # ── Drive the media-type filter (books vs. audiobooks vs. magazines).
    record_type = _single_char_or_none(_first_js_field(tree, "ld06"))
    bibliographic_level = _single_char_or_none(_first_js_field(tree, "ld07"))

    record = ParsedRecord(
        titn=titn,
        title=title.strip(),
        authors=tuple(a.strip() for a in authors if a.strip()),
        subjects=subjects,
        isbns=isbns,
        publisher=publisher or None,
        classification=classification or None,
        document_type=document_type,
        language=language,
        pub_year=pub_year,
        record_type=record_type,
        bibliographic_level=bibliographic_level,
    )

    # ── Copies ────────────────────────────────────────────────
    copies = tuple(_parse_copies(tree))

    return ParseResult(record=record, copies=copies)


_RESULTS_TOTAL_RE = re.compile(r"([\d.]+)\s+Registros", re.IGNORECASE)


def parse_search_results(html: str) -> SearchResultsPage:
    """Parse a DOSEARCH results-list page into TITNs + pagination info.

    AbsysNET embeds each result's TITN in a `js-TITN` span (same convention
    as the record page) and paginates via an ``<a aria-label="Siguiente">``
    whose href carries the session token + a ``DOC=`` offset. Validated
    against ``tests/catalog/fixtures/search_novedades.html``.
    """
    if not html or not html.strip():
        msg = "Cannot parse empty results HTML"
        raise ParseError(msg)
    tree = HTMLParser(html)

    titns: list[int] = []
    seen: set[int] = set()
    for node in tree.css(".js-TITN"):
        text = node.text(strip=True)
        if not text:
            continue
        try:
            value = int(text)
        except ValueError:
            continue
        if value not in seen:
            seen.add(value)
            titns.append(value)

    return SearchResultsPage(
        titns=tuple(titns),
        next_url=_extract_next_page(tree),
        total=_extract_results_total(tree),
    )


def _extract_next_page(tree: HTMLParser) -> str | None:
    """The 'Siguiente' control's href, or None when there's no next page.

    On the last page the control is absent or disabled, so it won't carry a
    usable ``DOC=`` offset — we treat that as 'no more pages'.
    """
    node = tree.css_first('a[aria-label="Siguiente"]') or tree.css_first('a[title="Siguiente"]')
    if node is None:
        return None
    href = node.attributes.get("href")
    if not href or "abnetcl.cgi" not in href or "DOC=" not in href:
        return None
    return href


def _extract_results_total(tree: HTMLParser) -> int | None:
    match = _RESULTS_TOTAL_RE.search(tree.text())
    if match is None:
        return None
    try:
        return int(match.group(1).replace(".", ""))
    except ValueError:
        return None


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


# MARC 6XX subject-access fields the OPAC may expose, in priority order.
# T650 (topical term) dominates; the rest appear only on richer records.
# AbsysNET renders each as a `js-T6xx` span, same convention as every other
# MARC field, so we reuse `_all_js_fields`. NOTE: the canonical titn_1
# fixture (a poetry collection) carries no 6XX headings, so this extraction
# is exercised by synthetic snippets in the tests — re-confirm the exact
# `js-` class against a record known to have materias on the next live crawl.
_SUBJECT_FIELDS: tuple[str, ...] = ("T650", "T651", "T655", "T600", "T610", "T611", "T630")


def _extract_subjects(tree: HTMLParser) -> list[str]:
    """Collect MARC 6XX subject headings into one ordered, deduped list.

    First-seen order is preserved and exact duplicates are dropped, so a
    heading repeated across subfields (e.g. T650 and T655) appears once.
    """
    out: list[str] = []
    seen: set[str] = set()
    for code in _SUBJECT_FIELDS:
        for value in _all_js_fields(tree, code):
            if value not in seen:
                seen.add(value)
                out.append(value)
    return out


def _extract_isbns(tree: HTMLParser) -> list[str]:
    """Collect MARC 020 $a ISBNs, normalized to ISBN-13, first-seen order.

    AbsysNET renders the clean ISBN as `js-T020a`; the `js-T020aq` variant
    carries trailing qualifier junk, so we target `T020a` exactly. ISBN-10s
    are converted to ISBN-13 (the form the `covers` context is keyed on);
    unparseable values are dropped.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in _all_js_fields(tree, "T020a"):
        isbn = _normalize_isbn(raw)
        if isbn is not None and isbn not in seen:
            seen.add(isbn)
            out.append(isbn)
    return out


# ISBN normalization is shared with the Goodreads matcher (reading_history),
# so the canonical implementation lives in the catalog domain. Keep the private
# alias here so existing call sites read naturally.
_normalize_isbn = normalize_to_isbn13


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


# Plausible publication-year band. FEPU often carries MARC "unknown date"
# sentinels (most commonly 9999, also 0000/uuuu) which must NOT be stored as a
# real year — they'd print as "9999" in the UI and (before the relevance fix)
# skewed recency. Anything outside the band is treated as unknown (None).
#
# The upper bound is the *current* year plus a small buffer, not a fixed 2100:
# libraries catalogue forthcoming titles a little ahead of publication, but a
# record dated 2029 or 2033 is a source-data error (MARC typo, or the T260
# regex catching a non-year 4-digit run) and must not be stored as a real year
# — especially since browse sorts by pub_year desc, floating these to the top.
_MIN_PLAUSIBLE_PUB_YEAR = 1
_PUB_YEAR_FUTURE_BUFFER = 1  # tolerate next-year imprints for forthcoming titles


def _max_plausible_pub_year(now: datetime | None = None) -> int:
    return (now or datetime.now(UTC)).year + _PUB_YEAR_FUTURE_BUFFER


def _extract_pub_year(tree: HTMLParser, *, max_year: int | None = None) -> int | None:
    """Pub year from `js-FEPU` if present; otherwise from a 4-digit run in T260.

    Out-of-band values (the 9999 MARC 'unknown date' sentinel, 0, and future
    years beyond next year) are normalised to ``None`` — an unknown year is
    stored as NULL, never as a bogus number. ``max_year`` defaults to the
    current year plus a one-year buffer; tests pass it explicitly.
    """
    if max_year is None:
        max_year = _max_plausible_pub_year()

    def _in_band(year: int) -> bool:
        return _MIN_PLAUSIBLE_PUB_YEAR <= year <= max_year

    fepu = _first_js_field(tree, "FEPU")
    if fepu and fepu.isdigit() and len(fepu) >= 4:
        year = int(fepu[:4])
        if _in_band(year):
            return year
    t260 = _first_js_field(tree, "T260")
    if t260:
        m = re.search(r"\b(1[4-9]\d{2}|20\d{2}|21\d{2})\b", t260)
        if m and _in_band(int(m.group(1))):
            return int(m.group(1))
    return None


def _parse_copies(tree: HTMLParser) -> list[ParsedCopy]:
    """Walk every `<div class="copias_data js-copias_data">` block and
    emit one ParsedCopy per ejemplar (per ``<tr data-disp="…">`` row).

    HTML structure (simplified):

        <div class="copias_data js-copias_data">
            <h3 id="copias_bibBIAN"><span>Biblioteca de Andalucía</span></h3>
            <div class="copias_accordion">
                <div class="c-accordion_item">
                    <button id="copias_accordionBtn_900">…</button>
                    <section><table data-code="900" …>
                        <tbody>
                            <tr data-disp="Disponible">
                                …<a data-sign="3-B-522" data-bc="7555638">…
                                <td class="copias_tableDisp">…<span>Disponible</span>
                            </tr>
                            …more ejemplares…
                        </tbody>
                    </table></section>
                </div>
            </div>
        </div>

    If a biblioteca block has no ejemplar rows (virtual-only items, or
    closed sucursales) we still emit one synthetic ParsedCopy with the
    biblioteca code/name so the holdings layer knows the record is
    present at that branch — just without per-ejemplar detail.
    """
    out: list[ParsedCopy] = []
    seen_keys: set[tuple[str, str | None]] = set()

    for block in tree.css(".copias_data.js-copias_data"):
        block_html = block.html or ""
        code = _branch_code_from_block(block_html)
        name = _branch_name_from_block(block_html)
        if not code or not name:
            continue

        ejemplares = _parse_ejemplares_in_block(block_html)
        if not ejemplares:
            # No per-ejemplar rows — keep the biblioteca presence marker.
            placeholder_key: tuple[str, str | None] = (code, None)
            if placeholder_key not in seen_keys:
                seen_keys.add(placeholder_key)
                out.append(ParsedCopy(branch_code=code, branch_name=name))
            continue

        for ej in ejemplares:
            # De-dupe within a block by (code, barcode). Without a barcode
            # we fall back to (code, signature) since a real OPAC always
            # exposes at least one of the two.
            uniq = ej.barcode or ej.signature
            key: tuple[str, str | None] = (code, uniq)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(
                ParsedCopy(
                    branch_code=code,
                    branch_name=name,
                    signature=ej.signature,
                    barcode=ej.barcode,
                    raw_status=ej.raw_status,
                )
            )

    return out


@dataclass(frozen=True, slots=True)
class _EjemplarRow:
    """Internal helper — the per-row fields extracted from one ``<tr data-disp>``."""

    signature: str | None
    barcode: str | None
    raw_status: str | None


_BRANCH_ID_RE = re.compile(r'id="copias_bib([A-Za-z0-9]+)"')
_BRANCH_NAME_RE = re.compile(
    r'<span class="h-hdd">Biblioteca:\s*</span>\s*<span[^>]*>([^<]+)</span>',
    re.IGNORECASE,
)

# `<tr data-disp="...">...</tr>` — non-greedy body capture so adjacent rows
# don't get swallowed. We don't try to be clever about nested <table>s
# (AbsysNET doesn't nest them inside ejemplar rows).
_EJEMPLAR_TR_RE = re.compile(
    r'<tr\s+data-disp="([^"]+)"[^>]*>(.*?)</tr>',
    re.IGNORECASE | re.DOTALL,
)
_SIGN_ATTR_RE = re.compile(r'data-sign="([^"]+)"', re.IGNORECASE)
_BC_ATTR_RE = re.compile(r'data-bc="([^"]+)"', re.IGNORECASE)


def _parse_ejemplares_in_block(block_html: str) -> list[_EjemplarRow]:
    """Pull every ejemplar row out of one biblioteca block."""
    rows: list[_EjemplarRow] = []
    for disp, body in _EJEMPLAR_TR_RE.findall(block_html):
        sig_m = _SIGN_ATTR_RE.search(body)
        bc_m = _BC_ATTR_RE.search(body)
        rows.append(
            _EjemplarRow(
                signature=(sig_m.group(1).strip() if sig_m else None) or None,
                barcode=(bc_m.group(1).strip() if bc_m else None) or None,
                raw_status=(disp.strip() or None),
            )
        )
    return rows


def _single_char_or_none(value: str | None) -> str | None:
    """Normalise a MARC leader extraction — strip + lowercase, expect 1 char."""
    if value is None:
        return None
    stripped = value.strip().lower()
    if len(stripped) != 1:
        return None
    return stripped


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
