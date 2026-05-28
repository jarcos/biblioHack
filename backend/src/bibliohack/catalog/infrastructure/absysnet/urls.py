"""AbsysNET URL builders.

Pure functions. No I/O, no side effects. Each helper produces a fully-formed,
deterministic URL string that the HTTP adapter will fetch.

Reference: Comunidad Baratz documentation on stable URLs and direct queries:
- https://www.comunidadbaratz.com/blog/como-crear-urls-estables-al-opac-de-absysnet-y-no-morir-en-el-intento/
- https://www.comunidadbaratz.com/blog/como-lanzar-consultas-bibliograficas-a-absysnet-traves-de-la-url-del-opac/

The xsqf01..xsqf99 variables correspond to bibliographic fields; ACC=DOSEARCH
runs a search; TITN=N returns a record permalink (resolves to ACC=161 with a
session token after redirect).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from urllib.parse import quote_plus

if TYPE_CHECKING:
    from bibliohack.catalog.domain.titn import Titn

# ────────────────────────────────────────────────────────────
# Endpoint configuration
# ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AbsysnetEndpoints:
    """Per-installation endpoints. Defaults point at Andalucía (RBPA).

    For another AbsysNET install (e.g. a different autonomous region), swap
    the `base_url` and you have a new adapter for free.
    """

    base_url: str = "https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi"


DEFAULT_ENDPOINTS: Final = AbsysnetEndpoints()


# ────────────────────────────────────────────────────────────
# Search fields — the xsqf0N family
# ────────────────────────────────────────────────────────────


class SearchField(StrEnum):
    """Bibliographic field codes accepted by AbsysNET's `xsqf0N` parameters.

    `EXPERT` (xsqf99) accepts the AbsysNET expert-query syntax — operators
    like `y`, `o`, `adj`, `mismo`, and field-coded queries such as
    `(comic.t650.)` or `(@fepu>=2015)`.
    """

    ANY = "xsqf01"
    TITLE = "xsqf02"
    AUTHOR = "xsqf03"
    PUBLISHER = "xsqf04"
    SUBJECT = "xsqf05"
    COLLECTION = "xsqf06"
    DATE_FROM = "xsqf07"
    DATE_TO = "xsqf08"
    EXPERT = "xsqf99"


# ────────────────────────────────────────────────────────────
# Builders
# ────────────────────────────────────────────────────────────


def build_record_url(
    titn: Titn,
    *,
    endpoints: AbsysnetEndpoints = DEFAULT_ENDPOINTS,
) -> str:
    """Build the stable permalink for a record by TITN.

    AbsysNET will 302-redirect this to a session-tokenised URL of the shape
    `/abnetcl.cgi/{SESSION}?ACC=161`. That redirect is honoured by the HTTP
    adapter; callers always use the canonical TITN URL.

    Example:
        >>> build_record_url(Titn(12345))
        'https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?TITN=12345'
    """
    return f"{endpoints.base_url}?TITN={int(titn)}"


def build_search_url(
    field: SearchField,
    terms: str,
    *,
    branch: str | None = None,
    endpoints: AbsysnetEndpoints = DEFAULT_ENDPOINTS,
) -> str:
    """Build a direct-search URL targeting a single bibliographic field.

    `terms` may contain spaces; they are URL-encoded as `+` (per AbsysNET's
    expectations). For expert queries, prefer :func:`build_expert_url`, which
    is clearer at the call site.

    `branch` (the `SUBC` parameter) restricts a *display* to a given branch /
    sub-library when the user later opens an item from the result list. It
    does **not** filter the search itself — that's what `xsqfXX` is for.

    Example:
        >>> build_search_url(SearchField.TITLE, "cazadores de sombras")
        'https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?ACC=DOSEARCH&xsqf02=cazadores+de+sombras'
    """
    encoded = quote_plus(terms.strip())
    url = f"{endpoints.base_url}?ACC=DOSEARCH&{field.value}={encoded}"
    if branch is not None:
        url += f"&SUBC={quote_plus(branch)}"
    return url


def build_expert_url(
    expression: str,
    *,
    branch: str | None = None,
    endpoints: AbsysnetEndpoints = DEFAULT_ENDPOINTS,
) -> str:
    """Build an AbsysNET expert query (xsqf99).

    The `expression` is AbsysNET's mini-query language — operators `y` (AND),
    `o` (OR), `adj` (adjacency), `mismo`, plus field-coded predicates like
    `(@fepu>=2015)` (publication date) or `(@copi>=20200101)` (copy date).

    Example — books cataloged after 2020-01-01:
        >>> build_expert_url("(@copi>=20200101)")
        'https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?ACC=DOSEARCH&xsqf99=(%40copi%3E%3D20200101)'
    """
    encoded = quote_plus(expression.strip())
    url = f"{endpoints.base_url}?ACC=DOSEARCH&xsqf99={encoded}"
    if branch is not None:
        url += f"&SUBC={quote_plus(branch)}"
    return url


def build_new_records_url(
    *,
    since_yyyymmdd: int,
    endpoints: AbsysnetEndpoints = DEFAULT_ENDPOINTS,
) -> str:
    """Records added to circulation since a given date (refresh sweep).

    Uses the `@copi` (copy / acquisition date) predicate. Date is an integer
    in `YYYYMMDD` form, matching AbsysNET's internal representation.

    Example:
        >>> build_new_records_url(since_yyyymmdd=20260101)
        'https://www.juntadeandalucia.es/cultura/absys/abnopac/abnetcl.cgi?ACC=DOSEARCH&xsqf99=(%40copi%3E%3D20260101)'
    """
    return build_expert_url(f"(@copi>={since_yyyymmdd})", endpoints=endpoints)
