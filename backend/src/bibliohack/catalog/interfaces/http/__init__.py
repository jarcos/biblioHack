"""catalog — HTTP interface (FastAPI routers + Pydantic response schemas)."""

from bibliohack.catalog.interfaces.http.router import router

__all__ = ["router"]
