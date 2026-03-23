from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from routes.notifications import router as notifications_router
MSK = timezone(timedelta(hours=3))

pytestmark = pytest.mark.anyio


def _seed_streamer(fake_db, streamer_id: int = 5001, game_id: int = 32982, game_name: str = "Grand Theft Auto V") -> None:
    fake_db.streamers_by_id[streamer_id] = {
        "streamer_id": streamer_id,
        "streamer_name": "StreamerOne",
        "is_online": True,
        "is_pinned": False,
        "started_at": None,
        "priority": 1,
        "pr_slots": 2,
        "game_id": game_id,
        "game_name": game_name,
        "stream_title": "Amazing stream",
        "stream_thumbnail_url": "https://img.test/thumb.jpg",
        "profile_image_url": "https://img.test/profile.jpg",
        "added_at": datetime.now(MSK),
        "added_by_id": 10,
        "assignments": [],
        "assigned_pr_id": None,
    }


def _notification_principal() -> dict[str, object]:
    return {
        "principal_type": "service",
        "service_name": "discord_service",
        "permissions": {
            "notifications.render": True,
        },
    }


async def _client(build_api_app):
    app = build_api_app(
        notifications_router,
        current_user=_notification_principal(),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_render_notification_invalid_event_type(build_api_app) -> None:
    async with await _client(build_api_app) as client:
        response = await client.get("/api/notifications/render/invalid?streamer_id=1")

    assert response.status_code == 400


async def test_render_notification_old_stream_online_returns_400(build_api_app, fake_db) -> None:
    """Old stream_online type should no longer be valid."""
    _seed_streamer(fake_db, 5010)
    fake_db.guild_settings = {
        "notification_channel_id": 12345,
        "notification_templates": {},
    }
    async with await _client(build_api_app) as client:
        response = await client.get("/api/notifications/render/stream_online?streamer_id=5010")

    assert response.status_code == 400


async def test_render_notification_not_found_cases(build_api_app, fake_db) -> None:
    async with await _client(build_api_app) as client:
        missing_streamer = await client.get(
            "/api/notifications/render/stream_online_gta?streamer_id=999"
        )

    assert missing_streamer.status_code == 404

    _seed_streamer(fake_db, 5002)
    async with await _client(build_api_app) as client:
        missing_settings = await client.get(
            "/api/notifications/render/stream_online_gta?streamer_id=5002"
        )

    assert missing_settings.status_code == 404


async def test_render_notification_stream_online_gta_with_claim_button(
    build_api_app, fake_db
) -> None:
    _seed_streamer(fake_db, 5003)
    fake_db.guild_settings = {
        "notification_channel_id": 12345,
        "notification_templates": {
            "stream_online_gta": "{streamer_name} started GTA: {streamer_link}",
        },
    }

    async with await _client(build_api_app) as client:
        response = await client.get(
            "/api/notifications/render/stream_online_gta?streamer_id=5003"
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert "StreamerOne started GTA" in data["message"]
    assert data["component_spec"]["show_claim_button"] is True
    assert data["notification_channel_id"] == 12345


async def test_render_notification_stream_online_other_without_claim_button(
    build_api_app, fake_db
) -> None:
    _seed_streamer(fake_db, 5004, game_id=509658, game_name="Just Chatting")
    fake_db.guild_settings = {
        "notification_channel_id": 1,
        "notification_templates": {
            "stream_online_other": "{streamer_name} now live",
        },
    }

    async with await _client(build_api_app) as client:
        response = await client.get(
            "/api/notifications/render/stream_online_other?streamer_id=5004"
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["component_spec"]["show_claim_button"] is False
    assert "StreamerOne now live" in data["message"]


async def test_notification_channel_endpoint_removed(build_api_app, fake_db) -> None:
    async with await _client(build_api_app) as client:
        response = await client.get("/api/notifications/channel")

    assert response.status_code == 404
