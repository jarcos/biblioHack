"""WDQS SPARQL: the canon-seed query builder + result parser (pure, no I/O).

Kept free of httpx so the query text and the binding→:class:`CanonSeedWork`
mapping are unit-testable without hitting the network. The live client
(``client.py``) only adds pagination, politeness, and JSON transport.

Query shape (see ``docs/design/canon-import.md`` → "The canon seed builder"):
literary works (``wdt:P31/wdt:P279* wd:Q7725634``) that are notable enough
(Wikipedia sitelink count ≥ a floor) and are either in Spanish
(``wdt:P407 wd:Q1321``) or carry a literary award (``wdt:P166``). Per work we
pull label, author label, publication year, ISBN-13 (P212) / ISBN-10 (P957),
award labels, and the sitelink count.

Two practicalities shape the SPARQL:

* **One row per work.** ISBNs and awards are folded with ``GROUP_CONCAT`` so a
  work with three editions and two awards is a single row, not six. The
  domain re-cleans/dedups the concatenated values anyway.
* **Stable, cheap pagination.** ``ORDER BY ?work`` (a bound QID, not a computed
  aggregate) keeps ``LIMIT``/``OFFSET`` deterministic across pages and avoids
  the sort-the-whole-universe cost that trips the ~60s WDQS timeout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bibliohack.catalog.domain.canon import CanonSeedWork, CanonSource

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# Wikidata entity IDs we reference.
_Q_LITERARY_WORK = "Q7725634"  # "literary work"
_Q_SPANISH = "Q1321"  # "Spanish" (language)

_CONCAT_SEP = "␟"  # ␟ unit separator — won't appear inside a label/ISBN.

# Pagination + politeness defaults (the client may override).
DEFAULT_PAGE_SIZE = 500
DEFAULT_MIN_SITELINKS = 8


def build_canon_query(
    *,
    min_sitelinks: int = DEFAULT_MIN_SITELINKS,
    spanish_only: bool = False,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> str:
    """Render one page of the canon-seed SPARQL query.

    ``min_sitelinks`` is the notability floor (bounds the result set so the
    builder pulls a few thousand → low tens of thousands of works, not all of
    Wikidata). ``spanish_only`` drops the award branch and requires the work to
    be in Spanish; otherwise we take Spanish-language *or* award-bearing works.
    """
    if spanish_only:
        scope = f"?work wdt:P407 wd:{_Q_SPANISH} ."
    else:
        scope = (
            "{ ?work wdt:P407 wd:" + _Q_SPANISH + " . }\n  UNION\n  { ?work wdt:P166 ?_anyAward . }"
        )
    return f"""\
SELECT ?work ?workLabel ?authorLabel (MIN(?year) AS ?pubYear)
       (GROUP_CONCAT(DISTINCT ?isbn13; separator="{_CONCAT_SEP}") AS ?isbn13s)
       (GROUP_CONCAT(DISTINCT ?isbn10; separator="{_CONCAT_SEP}") AS ?isbn10s)
       (GROUP_CONCAT(DISTINCT ?awardLabel; separator="{_CONCAT_SEP}") AS ?awards)
       (SAMPLE(?sitelinks) AS ?notability)
WHERE {{
  ?work wdt:P31/wdt:P279* wd:{_Q_LITERARY_WORK} .
  ?work wikibase:sitelinks ?sitelinks .
  FILTER(?sitelinks >= {int(min_sitelinks)})
  {scope}
  OPTIONAL {{ ?work wdt:P50 ?author . }}
  OPTIONAL {{ ?work wdt:P577 ?pubdate . BIND(YEAR(?pubdate) AS ?year) }}
  OPTIONAL {{ ?work wdt:P212 ?isbn13 . }}
  OPTIONAL {{ ?work wdt:P957 ?isbn10 . }}
  OPTIONAL {{
    ?work wdt:P166 ?award .
    ?award rdfs:label ?awardLabel .
    FILTER(LANG(?awardLabel) = "es")
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en" . }}
}}
GROUP BY ?work ?workLabel ?authorLabel
ORDER BY ?work
LIMIT {int(limit)} OFFSET {int(offset)}
"""


def _binding_value(row: Mapping[str, Any], key: str) -> str | None:
    cell = row.get(key)
    if not isinstance(cell, dict):
        return None
    value = cell.get("value")
    return value if isinstance(value, str) and value != "" else None


def _qid_from_uri(uri: str | None) -> str | None:
    """``http://www.wikidata.org/entity/Q42`` → ``Q42``."""
    if not uri:
        return None
    return uri.rsplit("/", 1)[-1]


def _split_concat(value: str | None) -> list[str]:
    return [part for part in value.split(_CONCAT_SEP) if part] if value else []


def _to_int(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _to_year(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_bindings(rows: Sequence[Mapping[str, Any]]) -> list[CanonSeedWork]:
    """Map raw SPARQL JSON ``results.bindings`` rows to clean seed works.

    Rows without a usable QID or label are skipped (a malformed page shouldn't
    abort a refresh). Domain construction re-cleans ISBNs/awards and clamps the
    year, so this layer just shuttles strings across.
    """
    works: list[CanonSeedWork] = []
    for row in rows:
        qid = _qid_from_uri(_binding_value(row, "work"))
        title = _binding_value(row, "workLabel")
        # A label that's still the bare QID means the label service found no
        # human-readable name — treat as unusable.
        if qid is None or title is None or title == qid:
            continue
        isbns = _split_concat(_binding_value(row, "isbn13s")) + _split_concat(
            _binding_value(row, "isbn10s")
        )
        works.append(
            CanonSeedWork(
                source=CanonSource.WIKIDATA,
                source_ref=qid,
                title=title,
                author=_binding_value(row, "authorLabel"),
                pub_year=_to_year(_binding_value(row, "pubYear")),
                isbn13=tuple(isbns),
                awards=tuple(_split_concat(_binding_value(row, "awards"))),
                notability=_to_int(_binding_value(row, "notability")),
            )
        )
    return works
