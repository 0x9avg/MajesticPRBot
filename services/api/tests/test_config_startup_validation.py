from __future__ import annotations

import pytest

from config import Settings


def _make_settings(**overrides) -> Settings:
    payload = {
        "DB_HOST": "localhost",
        "DB_PORT": 3306,
        "DB_USER": "root",
        "DB_PASSWORD": "super-secret-db-password",
        "DB_NAME": "prmajesticbot",
        "JWT_SECRET_KEY": "x" * 32,
        "RABBITMQ_HOST": "localhost",
        "RABBITMQ_PORT": 5672,
        "RABBITMQ_USER": "guest",
        "RABBITMQ_PASSWORD": "guest",
        "RABBITMQ_VHOST": "/",
        "SERVICE_TOKENS": (
            "discord_service:discord-secret,"
            "twitch_service:twitch-secret"
        ),
    }
    payload.update(overrides)
    return Settings(_env_file=None, **payload)


def test_validate_service_startup_accepts_complete_runtime_config() -> None:
    settings = _make_settings()

    settings.validate_service_startup()


def test_validate_service_startup_rejects_missing_db_port() -> None:
    settings = _make_settings(DB_PORT=0)

    with pytest.raises(ValueError, match="DB_PORT must be a positive integer"):
        settings.validate_service_startup()


def test_validate_database_config_rejects_placeholder_password() -> None:
    settings = _make_settings(DB_PASSWORD="change_me")

    with pytest.raises(ValueError, match="DB_PASSWORD must not use a placeholder value"):
        settings.validate_database_config()


def test_validate_service_tokens_contract_rejects_placeholder_tokens() -> None:
    settings = _make_settings(
        SERVICE_TOKENS=(
            "discord_service:replace_with_discord_service_token,"
            "twitch_service:twitch-secret"
        )
    )

    with pytest.raises(ValueError, match="placeholder value"):
        settings.validate_service_tokens_contract()


def test_validate_production_security_rejects_insecure_cookie_and_http_panel_url() -> None:
    settings = _make_settings(
        ENV="production",
        COOKIE_SECURE=False,
        WEB_PANEL_URL="http://panel.example.com",
    )

    with pytest.raises(SystemExit):
        settings.validate_production_security()
