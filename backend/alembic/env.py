"""Alembic env.py — settings-driven, single Base metadata.

Runs migrations either offline (`alembic upgrade --sql`) or online with a
*synchronous* engine. The connection URL comes from our Settings, not
alembic.ini — that way local dev, CI, the Docker stack and integration
tests all read the same source of truth.

We deliberately use the sync engine here even though the rest of the app
is async:

- Migrations don't benefit from async (one connection, sequential DDL).
- The async variant tripped over pytest-asyncio's already-running event
  loop in integration tests (`asyncio.run` can't be called when a loop
  is already running).
- Sync is simpler to reason about for DDL — no `run_sync` indirection.

Settings exposes both `database_url` (asyncpg) and `database_url_sync`
(psycopg). We pick the sync one for Alembic.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import every model so that `Base.metadata` knows about every table.
# Adding a new bounded context with persistence means adding an import here.
from bibliohack.catalog.infrastructure.postgres import models as _catalog_models  # noqa: F401
from bibliohack.holdings.infrastructure.postgres import models as _holdings_models  # noqa: F401
from bibliohack.reading_history.infrastructure.postgres import (  # noqa: F401
    models as _reading_history_models,
)
from bibliohack.shared.infrastructure.db import Base
from bibliohack.shared.infrastructure.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the SYNC URL from settings (overrides whatever was in alembic.ini).
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a DB connection (writes SQL to stdout)."""
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a synchronous engine."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
