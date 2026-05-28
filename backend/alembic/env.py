"""Alembic env.py — async-aware, settings-driven, single Base metadata.

Runs migrations either offline (`alembic upgrade --sql`) or online via the
async engine. The connection URL comes from our Settings, not alembic.ini —
that way local dev, CI, and the Docker stack all read the same source of
truth.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

# Import every model so that `Base.metadata` knows about every table.
# Adding a new bounded context with persistence means adding an import here.
from bibliohack.catalog.infrastructure.postgres import models as _catalog_models  # noqa: F401
from bibliohack.holdings.infrastructure.postgres import models as _holdings_models  # noqa: F401
from bibliohack.shared.infrastructure.db import Base
from bibliohack.shared.infrastructure.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the URL from settings (overrides whatever was in alembic.ini).
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a DB connection (writes SQL to stdout)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against the async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
