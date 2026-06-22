"""HTTP interface for the holdings context (/api/branches, /api/me/branches)."""

from bibliohack.holdings.interfaces.http.branches_router import router as branches_router

__all__ = ["branches_router"]
