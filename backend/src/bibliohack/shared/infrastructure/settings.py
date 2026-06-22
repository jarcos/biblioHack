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
    database_url_sync: str = "postgresql+psycopg://bibliohack:bibliohack@localhost:5432/bibliohack"

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
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ───── Recommendations (§4 / M5) ─────
    recommendations_limit: int = 12

    # ───── Embeddings ─────
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: Literal["cpu", "cuda", "mps"] = "cpu"
    # Hosted embeddings via the HuggingFace Inference API (BGE-M3, 1024-d) —
    # keeps the model off the RAM-constrained NAS. Token is a free HF read
    # token, set in the environment (HUGGINGFACE_API_TOKEN).
    huggingface_api_token: str = ""
    huggingface_embedding_endpoint: str = (
        "https://router.huggingface.co/hf-inference/models/BAAI/bge-m3/pipeline/feature-extraction"
    )

    # ───── Covers (§7.5) ─────
    # Content-addressed cover store root. Filesystem for now (dev + NAS
    # volume); a MinIO/S3 CoverStore is a drop-in behind the same port.
    covers_store_path: str = "~/biblioHack-data/covers"
    covers_user_agent: str = "bibliohack/0.1 (+https://biblio.josearcos.me)"

    # ───── Branch geocoding (Libraries L0) ─────
    # Nominatim's usage policy requires a descriptive UA with contact info.
    nominatim_user_agent: str = (
        "bibliohack/0.1 (+https://biblio.josearcos.me; josearcoscampos@gmail.com)"
    )

    # ───── Identity / auth (§4) ─────
    # Public base URL used in emails (verification / password-reset links).
    public_base_url: str = "https://biblio.josearcos.me"
    # Sessions: opaque random ids stored server-side in Redis, delivered via
    # an httpOnly cookie. `secure` defaults False so plain-http local dev
    # works; production compose sets SESSION_COOKIE_SECURE=true.
    session_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 days
    session_cookie_name: str = "bibliohack_session"
    session_cookie_domain: str | None = None
    session_cookie_secure: bool = False
    # Argon2id parameters (argon2-cffi). Defaults match the library's
    # RFC-9106 low-memory profile; tune via env if NAS RAM allows more.
    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 65536
    argon2_parallelism: int = 4
    # Public registration kill-switch (abuse response: flip env var, restart).
    registration_enabled: bool = True
    # Require a verified email before login succeeds (public-registration
    # hygiene; relax in dev where no mailer is configured).
    require_verified_email_login: bool = True
    # NAS SMTP mailer. Empty host = mails are logged instead of sent (dev).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    mail_from: str = "biblioHack <no-reply@biblio.josearcos.me>"
    # Cloudflare Turnstile (register/login bot protection). Empty secret =
    # verification disabled (dev default); set both keys in production.
    turnstile_site_key: str = ""
    turnstile_secret: str = ""

    # ───── Shelf imports (background jobs) ─────
    # Guardrails on the public CSV upload: a Goodreads export of a few
    # thousand books is ~1-2 MB, so these caps are generous for real
    # libraries while keeping malicious uploads off the worker.
    import_max_upload_bytes: int = 5 * 1024 * 1024
    import_max_rows: int = 10_000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor. Cached so we only parse env once per process."""
    return Settings()
