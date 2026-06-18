"""Wikidata Query Service integration (off-OPAC canon-seed source)."""

from bibliohack.catalog.infrastructure.wikidata.client import WikidataCanonSource
from bibliohack.catalog.infrastructure.wikidata.query import (
    build_canon_query,
    parse_bindings,
)

__all__ = [
    "WikidataCanonSource",
    "build_canon_query",
    "parse_bindings",
]
