"""Tests for the AbsysNET HTML parser.

The canonical fixture is `tests/catalog/fixtures/titn_1.html` — a 189KB
real OPAC page captured from the live RBPA on 2026-05-28. We use it as the
golden reference for "what a normal record looks like". Smaller hand-crafted
snippets cover edge cases (missing fields, blank title, not-found page).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bibliohack.catalog.domain.titn import Titn
from bibliohack.catalog.infrastructure.absysnet.parser import (
    ParseError,
    looks_like_not_found,
    parse_record_html,
    parse_search_results,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ───────────────────────────────────────────────────────────────
# Real fixture: TITN=1 (0044 y medio IBM y compañía Arantza)
# ───────────────────────────────────────────────────────────────


@pytest.fixture
def titn_1_html() -> str:
    return (FIXTURES / "titn_1.html").read_text(encoding="utf-8")


def test_parses_real_titn_1_fixture(titn_1_html: str) -> None:
    result = parse_record_html(titn_1_html)
    assert result.record.titn == 1
    assert result.record.title == "0044 y medio IBM y compañía Arantza"


def test_parses_author_from_real_fixture(titn_1_html: str) -> None:
    result = parse_record_html(titn_1_html)
    assert "Bornoy, Pepe" in result.record.authors


def test_parses_publisher_from_real_fixture(titn_1_html: str) -> None:
    result = parse_record_html(titn_1_html)
    # Either bare publisher name or the joined "place : publisher" form;
    # the parser strips the place prefix when a colon is present.
    assert result.record.publisher is not None
    assert "Guadalhorce" in result.record.publisher


def test_parses_classification_from_real_fixture(titn_1_html: str) -> None:
    result = parse_record_html(titn_1_html)
    # T080 is the UDC code we observed for this record.
    assert result.record.classification == '821.134.2-1"19"'


def test_parses_marc_leader_positions_06_07_from_real_fixture(titn_1_html: str) -> None:
    """LDR/06 = 'a' (language material), LDR/07 = 'm' (monograph) — book."""
    result = parse_record_html(titn_1_html)
    assert result.record.record_type == "a"
    assert result.record.bibliographic_level == "m"


def test_real_titn_1_fixture_has_no_subjects(titn_1_html: str) -> None:
    """titn_1 is a poetry collection catalogued without 6XX materia headings.

    Documents the reality the classifier must tolerate — the subject parser
    must return an empty tuple here rather than inventing headings. The
    extraction logic itself is exercised on synthetic HTML below.
    """
    result = parse_record_html(titn_1_html)
    assert result.record.subjects == ()


def test_extracts_subjects_from_marc_6xx_spans() -> None:
    """T650/T651/T655 spans are folded into one ordered, deduped tuple."""
    html = """
    <html><body>
      <span class="js-TITN">5</span>
      <span class="js-T245">Una novela con materias</span>
      <span class="js-T650">Ciencia ficción</span>
      <span class="js-T650">Distopías</span>
      <span class="js-T651">Madrid (España)</span>
      <span class="js-T655">Novela</span>
      <span class="js-T650">Distopías</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.subjects == (
        "Ciencia ficción",
        "Distopías",
        "Madrid (España)",
        "Novela",
    )


def test_pub_year_sentinel_9999_normalised_to_none() -> None:
    """A MARC 'unknown date' sentinel in FEPU (9999) is stored as NULL, not a
    bogus year — otherwise it prints as '9999' and skews recency."""
    html = """
    <html><body>
      <span class="js-TITN">9</span>
      <span class="js-T245">Año desconocido</span>
      <span class="js-FEPU">9999</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.pub_year is None


def test_pub_year_real_fepu_year_is_kept() -> None:
    """A plausible FEPU year is parsed normally (regression guard for the clamp)."""
    html = """
    <html><body>
      <span class="js-TITN">10</span>
      <span class="js-T245">Novedad</span>
      <span class="js-FEPU">2026</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.pub_year == 2026


def test_subjects_empty_when_no_6xx_present() -> None:
    html = """
    <html><body>
      <span class="js-TITN">6</span>
      <span class="js-T245">Sin materias</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.subjects == ()


def test_parses_all_branches_from_real_fixture(titn_1_html: str) -> None:
    result = parse_record_html(titn_1_html)
    # 4 copies in 4 different branches per the live OPAC.
    branch_names = {c.branch_name for c in result.copies}
    branch_codes = {c.branch_code for c in result.copies}
    assert "Frailes" in branch_names
    assert "Antequera" in branch_names
    assert "Fuengirola" in branch_names
    assert "Biblioteca de Andalucía" in branch_names
    # Branch codes use the province + sequence convention.
    assert "JA23" in branch_codes  # Frailes (Jaén)
    assert "MA03" in branch_codes  # Antequera (Málaga)
    assert "MA15" in branch_codes  # Fuengirola (Málaga)


def test_parses_per_ejemplar_signature_and_barcode(titn_1_html: str) -> None:
    """Each ejemplar row exposes a `data-sign` / `data-bc` pair on its link."""
    result = parse_record_html(titn_1_html)
    by_branch = {c.branch_code: c for c in result.copies}
    # From the fixture: BIAN → signature 3-B-522, barcode 7555638.
    assert by_branch["BIAN"].signature == "3-B-522"
    assert by_branch["BIAN"].barcode == "7555638"
    # And the Frailes (JA23) ejemplar has its own signature/barcode.
    assert by_branch["JA23"].signature == "J-N SAL cab"
    assert by_branch["JA23"].barcode == "9593489"


def test_parses_raw_status_from_data_disp_attribute(titn_1_html: str) -> None:
    """The `data-disp` attribute on each `<tr>` carries the loan status."""
    result = parse_record_html(titn_1_html)
    by_branch = {c.branch_code: c for c in result.copies}
    # Three "Disponible" and one "En inventario" in this fixture.
    assert by_branch["BIAN"].raw_status == "Disponible"
    assert by_branch["JA23"].raw_status == "En inventario"
    assert by_branch["MA03"].raw_status == "Disponible"
    assert by_branch["MA15"].raw_status == "Disponible"


def test_emits_one_copy_per_ejemplar_row() -> None:
    """If a biblioteca has 3 ejemplares, we emit 3 ParsedCopy rows."""
    # `<a>` lives inside `<td>` because HTML5 foster-parenting moves bare
    # `<a>` children of `<tr>` out of the table. The real OPAC's nesting
    # is already <tr><td>...<a>...</a></td></tr>.
    html = """
    <html><body>
      <span class="js-TITN">7</span>
      <span class="js-T245">Multi-copy book</span>
      <div class="copias_data js-copias_data">
        <h3 id="copias_bibHU01">
          <span class="h-hdd">Biblioteca: </span>
          <span>Biblioteca Provincial de Huelva</span>
        </h3>
        <table data-code="100">
          <tbody>
            <tr data-disp="Disponible"><td><a data-sign="A 1" data-bc="111"></a></td></tr>
            <tr data-disp="Prestado"><td><a data-sign="A 2" data-bc="222"></a></td></tr>
            <tr data-disp="Disponible"><td><a data-sign="A 3" data-bc="333"></a></td></tr>
          </tbody>
        </table>
      </div>
    </body></html>
    """
    result = parse_record_html(html)
    statuses = sorted(c.raw_status or "" for c in result.copies)
    barcodes = sorted(c.barcode or "" for c in result.copies)
    assert len(result.copies) == 3
    assert statuses == ["Disponible", "Disponible", "Prestado"]
    assert barcodes == ["111", "222", "333"]
    # All three share the same biblioteca.
    assert {c.branch_code for c in result.copies} == {"HU01"}


def test_biblioteca_block_with_no_ejemplar_rows_still_emits_one_copy() -> None:
    """A biblioteca shown in the OPAC but with no expanded ejemplar table
    (e.g. virtual / digital copies) should still produce a placeholder
    ParsedCopy with raw_status=None."""
    html = """
    <html><body>
      <span class="js-TITN">8</span>
      <span class="js-T245">Virtual-only book</span>
      <div class="copias_data js-copias_data">
        <h3 id="copias_bibVIRT">
          <span class="h-hdd">Biblioteca: </span>
          <span>eBiblio</span>
        </h3>
        <!-- no <table> inside, no rows -->
      </div>
    </body></html>
    """
    result = parse_record_html(html)
    assert len(result.copies) == 1
    only = result.copies[0]
    assert only.branch_code == "VIRT"
    assert only.branch_name == "eBiblio"
    assert only.signature is None
    assert only.barcode is None
    assert only.raw_status is None


def test_expected_titn_assertion_matches(titn_1_html: str) -> None:
    # Defensive check passes when the page actually contains the expected TITN.
    result = parse_record_html(titn_1_html, expected_titn=Titn(1))
    assert result.record.titn == 1


def test_expected_titn_mismatch_raises(titn_1_html: str) -> None:
    with pytest.raises(ParseError, match="TITN mismatch"):
        parse_record_html(titn_1_html, expected_titn=Titn(999))


# ───────────────────────────────────────────────────────────────
# Edge cases on hand-crafted minimal HTML
# ───────────────────────────────────────────────────────────────


def test_empty_html_rejected() -> None:
    with pytest.raises(ParseError, match="empty HTML"):
        parse_record_html("")


def test_whitespace_only_html_rejected() -> None:
    with pytest.raises(ParseError, match="empty HTML"):
        parse_record_html("   \n   ")


def test_html_without_titn_rejected() -> None:
    with pytest.raises(ParseError, match="No TITN"):
        parse_record_html("<html><body><p>hello</p></body></html>")


def test_minimal_record_parses() -> None:
    html = """
    <html><body>
      <span class="js-TITN">42</span>
      <span class="js-T245">Some Title</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.titn == 42
    assert result.record.title == "Some Title"
    assert result.record.authors == ()
    assert result.record.publisher is None
    assert result.copies == ()


def test_fallback_title_from_doc_title_class() -> None:
    # Some records carry the title only in the visible doc_title span, not
    # in a js-T245 element. Parser should still recover.
    html = """
    <html><body>
      <span class="js-TITN">7</span>
      <span class="doc_title">Fallback Title Recovery</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.title == "Fallback Title Recovery"


def test_missing_title_rejected() -> None:
    html = '<html><body><span class="js-TITN">1</span></body></html>'
    with pytest.raises(ParseError, match="No title"):
        parse_record_html(html)


def test_publisher_strips_place_prefix_and_trailing_year() -> None:
    html = """
    <html><body>
      <span class="js-TITN">1</span>
      <span class="js-T245">x</span>
      <span class="js-T260">Madrid : Alianza Editorial, 2019</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.publisher == "Alianza Editorial"
    assert result.record.pub_year == 2019


def test_pub_year_via_fepu() -> None:
    html = """
    <html><body>
      <span class="js-TITN">1</span>
      <span class="js-T245">x</span>
      <span class="js-FEPU">20240315</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.pub_year == 2024


def test_pub_year_implausible_in_t260_is_ignored() -> None:
    # 1234 is not a plausible 1400-2100 year — the regex requires the modern range.
    html = """
    <html><body>
      <span class="js-TITN">1</span>
      <span class="js-T245">x</span>
      <span class="js-T260">Some random text 1234 not a year</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.pub_year is None


def test_pub_year_future_fepu_normalised_to_none() -> None:
    """A FEPU year well beyond next year (2033) is a source-data error and must
    be stored as NULL, not floated to the top of the catalogue by the
    pub_year-desc browse sort."""
    html = """
    <html><body>
      <span class="js-TITN">1</span>
      <span class="js-T245">x</span>
      <span class="js-FEPU">2033</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.pub_year is None


def test_pub_year_future_in_t260_normalised_to_none() -> None:
    """The T260 fallback regex matches any 20xx run; a future year (2029) must
    still be rejected by the plausibility band, not returned verbatim."""
    html = """
    <html><body>
      <span class="js-TITN">1</span>
      <span class="js-T245">x</span>
      <span class="js-T260">Madrid : Editorial, 2029</span>
    </body></html>
    """
    result = parse_record_html(html)
    assert result.record.pub_year is None


# ───────────────────────────────────────────────────────────────
# Not-found detection
# ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "snippet",
    [
        "Esta consulta NO recupera resultados",
        "el catálogo (0 docs.) coincidentes",
        "no se ha encontrado registro",
        "Registro no encontrado",
    ],
)
def test_looks_like_not_found_detects_markers(snippet: str) -> None:
    assert looks_like_not_found(snippet) is True


def test_looks_like_not_found_returns_false_on_real_record(titn_1_html: str) -> None:
    assert looks_like_not_found(titn_1_html) is False


def test_looks_like_not_found_handles_empty_string() -> None:
    assert looks_like_not_found("") is False


# ───────────────────────────────────────────────────────────────
# DOSEARCH results-list parsing (novedades discovery)
# ───────────────────────────────────────────────────────────────


@pytest.fixture
def search_results_html() -> str:
    """A real `xsqf99=(@fepu>=2023)` results page captured from the live OPAC."""
    return (FIXTURES / "search_novedades.html").read_text(encoding="utf-8")


def test_parses_search_results_titns(search_results_html: str) -> None:
    page = parse_search_results(search_results_html)
    # The RBPA OPAC shows 10 results per page; each carries a js-TITN span.
    assert len(page.titns) == 10
    assert 13168 in page.titns
    assert all(isinstance(t, int) for t in page.titns)


def test_parses_search_results_pagination_and_total(search_results_html: str) -> None:
    page = parse_search_results(search_results_html)
    assert page.next_url is not None
    assert "DOC=" in page.next_url
    assert page.total == 83607


def test_parse_search_results_rejects_empty() -> None:
    with pytest.raises(ParseError, match="empty results"):
        parse_search_results("")


def test_parse_search_results_no_next_on_last_page() -> None:
    html = '<html><body><span class="js-TITN">5</span><span class="js-TITN">9</span></body></html>'
    page = parse_search_results(html)
    assert page.titns == (5, 9)
    assert page.next_url is None
    assert page.total is None
