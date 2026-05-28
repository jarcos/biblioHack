"""Tests for application settings."""

from __future__ import annotations

import pytest

from bibliohack.shared.infrastructure import Settings, get_settings


def test_defaults_are_safe_for_local_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wipe relevant env vars so we observe the defaults, not whatever the CI sets.
    for var in (
        "APP_ENV",
        "APP_LOG_LEVEL",
        "DATABASE_URL",
        "OPENROUTER_API_KEY",
        "EMBEDDING_DEVICE",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.app_env == "development"
    assert settings.app_log_level == "INFO"
    assert "asyncpg" in settings.database_url
    assert settings.embedding_device == "cpu"


def test_get_settings_is_cached() -> None:
    a = get_settings()
    b = get_settings()
    assert a is b
