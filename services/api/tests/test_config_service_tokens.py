from __future__ import annotations

import pytest

from config import Settings


def _make_settings(raw: str) -> Settings:
    return Settings(_env_file=None, SERVICE_TOKENS=raw)


def test_service_tokens_strict_map_parses_required_principals() -> None:
    settings = _make_settings(
        "discord_service:discord-secret,twitch_service:twitch-secret"
    )

    assert settings.service_token_map == {
        "discord_service": "discord-secret",
        "twitch_service": "twitch-secret",
    }


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "discord_service:discord-secret",
        "discord_service:discord-secret,not_named_token",
        "discord_service:,twitch_service:twitch-secret",
        "discord_service:shared,twitch_service:shared",
        "discord_service:one,discord_service:two,twitch_service:three",
    ],
)
def test_service_tokens_strict_map_rejects_invalid_values(raw: str) -> None:
    settings = _make_settings(raw)

    with pytest.raises(ValueError):
        _ = settings.service_token_map


def test_validate_service_tokens_contract_raises_on_missing_required_service() -> None:
    settings = _make_settings("discord_service:discord-secret")

    with pytest.raises(ValueError):
        settings.validate_service_tokens_contract()
