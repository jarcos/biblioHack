"""AbsysNET adapter — URL builders, HTTP client, HTML parser.

Everything that knows about *how* AbsysNET works lives here. The rest of the
catalog context only sees ports.
"""

from bibliohack.catalog.infrastructure.absysnet.gateway import (
    GatewayConfig,
    ScraplingOpacGateway,
)
from bibliohack.catalog.infrastructure.absysnet.parser import (
    ParsedCopy,
    ParsedRecord,
    ParseError,
    ParseResult,
    looks_like_not_found,
    parse_record_html,
)
from bibliohack.catalog.infrastructure.absysnet.throttle import TokenBucket
from bibliohack.catalog.infrastructure.absysnet.urls import (
    AbsysnetEndpoints,
    build_record_url,
    build_search_url,
)

__all__ = [
    "AbsysnetEndpoints",
    "GatewayConfig",
    "ParseError",
    "ParseResult",
    "ParsedCopy",
    "ParsedRecord",
    "ScraplingOpacGateway",
    "TokenBucket",
    "build_record_url",
    "build_search_url",
    "looks_like_not_found",
    "parse_record_html",
]
