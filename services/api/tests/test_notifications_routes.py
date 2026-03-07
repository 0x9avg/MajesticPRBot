from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from routes.notifications import router as notifications_router
MSK = timezone(timedelta(hours=3))

pytestmark = pytest.mark.anyio


def _seed_streamer(fake_db, streamer_id: int = 5001) -> None:
    fake_db.streamers_by_id[streamer_id] = {
        "streamer_id": streamer_id,
        "streamer_name": "StreamerOne",
        "is_online": True,
        "is_pinned": False,
        "started_at": None,
        "priority": 1,
        "pr_slots": 2,
        "game_id": 32982,
        "game_name": "Grand Theft Auto V",
        "stream_title": "Amazing stream",
        "stream_thumbnail_url": "https://img.test/thumb.jpg",
        "profile_image_url": "https://img.test/profile.jpg",
        "added_at": datetime.now(MSK),
        "added_by_id": 10,
        "assignments": [],
        "assigned_pr_id": None,
    }


async def _client(build_api_app):
    app = build_api_app(notifications_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_render_notification_invalid_event_type(build_api_app) -> None:
    async with await _client(build_api_app) as client:
        response = await client.get("/api/notifications/render/invalid?streamer_id=1")

    assert response.status_code == 400


async def test_render_notification_not_found_cases(build_api_app, fake_db) -> None:
    async with await _client(build_api_app) as client:
        missing_streamer = await client.get(
            "/api/notifications/render/stream_online?streamer_id=999"
        )

    assert missing_streamer.status_code == 404

    _seed_streamer(fake_db, 5002)
    async with await _client(build_api_app) as client:
        missing_settings = await client.get(
            "/api/notifications/render/stream_online?streamer_id=5002"
        )

    assert missing_settings.status_code == 404


async def test_render_notification_success_with_claim_button(
    build_api_app, fake_db
) -> None:
    _seed_streamer(fake_db, 5003)
    fake_db.guild_settings = {
        "notification_channel_id": 12345,
        "notification_templates": {
            "stream_online": "{streamer_name} started {game_name}: {streamer_link}",
        },
    }

    async with await _client(build_api_app) as client:
        response = await client.get(
            "/api/notifications/render/stream_online?streamer_id=5003"
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert "StreamerOne started Grand Theft Auto V" in data["message"]
    assert data["component_spec"]["show_claim_button"] is True
    assert data["notification_channel_id"] == 12345


async def test_render_notification_without_claim_button_for_non_gta(
    build_api_app, fake_db
) -> None:
    _seed_streamer(fake_db, 5004)
    fake_db.streamers_by_id[5004]["game_id"] = 509658
    fake_db.streamers_by_id[5004]["game_name"] = "Just Chatting"
    fake_db.guild_settings = {
        "notification_channel_id": 1,
        "notification_templates": {
            "stream_online": "{streamer_name} now live",
        },
    }

    async with await _client(build_api_app) as client:
        response = await client.get(
            "/api/notifications/render/stream_online?streamer_id=5004"
        )

    assert response.status_code == 200
    assert response.json()["data"]["component_spec"]["show_claim_button"] is False


async def test_notification_channel_endpoint_removed(build_api_app, fake_db) -> None:
    async with await _client(build_api_app) as client:
        response = await client.get("/api/notifications/channel")

    assert response.status_code == 404
