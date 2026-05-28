"""Application settings, loaded from environment variables.

We use pydantic-settings so the settings object is a single source of truth that
is typed, validated at startup, and discoverable in tests via dependency
override.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Process-wide configuration, loaded from env vars / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ───── App ─────
    app_env: AppEnv = "development"
    app_log_level: str = "INFO"
    app_cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:4321"])

    # ───── Database ─────
    database_url: str = "postgresql+asyncpg://bibliohack:bibliohack@localhost:5432/bibliohack"
    database_url_sync: str = (
        "postgresql+psycopg://bibliohack:bibliohack@localhost:5432/bibliohack"
    )

    # ───── Redis ─────
    redis_url: str = "redis://localhost:6379/0"

    # ───── Scraper ─────
    scraper_user_agent: str = "bibliohack/0.1 (+https://github.com/your-user/biblioHack)"
    scraper_min_interval_seconds: float = 1.0
    scraper_max_interval_seconds: float = 1.8
    scraper_daily_request_cap: int = 30_000

    # ───── OpenRouter ─────
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/auto:free"

    # ───── Embeddings ─────
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: Literal["cpu", "cuda", "mps"] = "cpu"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor. Cached so we only parse env once per process."""
    return Settings()
