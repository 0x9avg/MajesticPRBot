from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from routes.guilds import router as guild_router

pytestmark = pytest.mark.anyio


async def _client(build_api_app, include_broker: bool = True):
    app = build_api_app(guild_router, include_broker=include_broker)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_guild_and_settings_autocreate(build_api_app, fake_db) -> None:
    assert fake_db.guild_settings is None

    async with await _client(build_api_app) as client:
        all_response = await client.get("/api/guild")
        settings_response = await client.get("/api/guild/settings")

    assert all_response.status_code == 200
    assert settings_response.status_code == 200
    assert fake_db.guild_settings is not None
    assert "notification_channel_id" in settings_response.json()["data"]


async def test_update_guild_settings_with_broker_event(
    build_api_app, fake_db, fake_broker
) -> None:
    async with await _client(build_api_app) as client:
        response = await client.patch(
            "/api/guild/settings",
            json={
                "notification_channel_id": 123,
                "monitoring_channel_id": 456,
                "monitoring_filter_gta": True,
            },
        )

    assert response.status_code == 200
    assert fake_db.guild_settings["notification_channel_id"] == 123
    assert fake_db.guild_settings["monitoring_channel_id"] == 456
    assert any(call[0] == "guild.settings.updated" for call in fake_broker.calls)


async def test_get_and_update_templates(build_api_app, fake_db, fake_broker) -> None:
    async with await _client(build_api_app) as client:
        initial = await client.get("/api/guild/templates")
        updated = await client.patch(
            "/api/guild/templates",
            json={"stream_online": "LIVE {streamer_name}", "stream_offline": "OFF {streamer_name}"},
        )

    assert initial.status_code == 200
    assert updated.status_code == 200
    templates = fake_db.guild_settings["notification_templates"]
    assert templates["stream_online"] == "LIVE {streamer_name}"
    assert templates["stream_offline"] == "OFF {streamer_name}"
    assert any(call[0] == "guild.templates.updated" for call in fake_broker.calls)


async def test_get_template_by_type_valid_and_invalid(build_api_app) -> None:
    async with await _client(build_api_app) as client:
        invalid = await client.get("/api/guild/templates/unknown")
        valid = await client.get("/api/guild/templates/stream_online")

    assert invalid.status_code == 400
    assert valid.status_code == 200
    assert valid.json()["data"]["event_type"] == "stream_online"


async def test_get_and_update_rates(build_api_app, fake_db, fake_broker) -> None:
    async with await _client(build_api_app) as client:
        initial = await client.get("/api/guild/rates")
        updated = await client.patch(
            "/api/guild/rates",
            json={"p0_rate": 1.1, "p1_rate": 1.3, "p2_rate": 1.7, "p3_rate": 2.1, "probation_rate": 1.25},
        )

    assert initial.status_code == 200
    assert updated.status_code == 200
    rates = updated.json()["data"]
    assert rates["p0_rate"] == 1.1
    assert rates["p3_rate"] == 2.1
    assert fake_db.guild_settings["probation_rate"] == 1.25
    assert any(call[0] == "guild.rates.updated" for call in fake_broker.calls)


async def test_update_endpoints_work_without_broker(build_api_app) -> None:
    async with await _client(build_api_app, include_broker=False) as client:
        settings = await client.patch("/api/guild/settings", json={"notification_channel_id": 555})
        templates = await client.patch("/api/guild/templates", json={"stream_online": "X"})
        rates = await client.patch("/api/guild/rates", json={"p0_rate": 1.11})

    assert settings.status_code == 200
    assert templates.status_code == 200
    assert rates.status_code == 200
