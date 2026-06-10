"""FastAPI application — composition root for the HTTP interface.

For M0 the app exposes only health and version endpoints. Domain routers are
added in M1 (catalog), M2 (availability), M3 (semantic search), M4 (imports),
M5 (recommendations).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bibliohack import __version__
from bibliohack.catalog.interfaces.http import router as catalog_router
from bibliohack.covers.interfaces.http.router import router as covers_router
from bibliohack.identity.interfaces.http.account_router import router as account_router
from bibliohack.identity.interfaces.http.router import router as auth_router
from bibliohack.interfaces.http.routers import health
from bibliohack.reading_history.interfaces.http.router import router as shelf_router
from bibliohack.recommendations.interfaces.http.router import router as recommendations_router
from bibliohack.shared.infrastructure import configure_logging, get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run startup/shutdown hooks once per process.

    The FastAPI app instance is part of the lifespan signature but we don't
    need it — settings are pulled from the process-wide cache.
    """
    settings = get_settings()
    configure_logging(settings)
    log = structlog.get_logger()
    log.info("app.startup", env=settings.app_env, version=__version__)
    try:
        yield
    finally:
        log.info("app.shutdown")


def create_app() -> FastAPI:
    """Application factory. Useful for tests, which create a fresh app per case."""
    settings = get_settings()

    app = FastAPI(
        title="biblioHack",
        version=__version__,
        description=(
            "Reverse catalog and AI-driven recommender for the Andalusian public-library network."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(catalog_router)
    app.include_router(covers_router)
    app.include_router(shelf_router)
    app.include_router(recommendations_router)

    return app


app = create_app()
