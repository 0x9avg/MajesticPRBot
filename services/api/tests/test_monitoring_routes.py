from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from routes.monitoring import router as monitoring_router

MSK = timezone(timedelta(hours=3))

pytestmark = pytest.mark.anyio


def _developer_user() -> dict:
    return {
        "id": 99,
        "username": "dev",
        "nickname": "Dev",
        "role": "developer",
        "principal_type": "user",
        "discord_id": 9099,
        "require_password_change": False,
        "permissions": {
            "monitoring.view": True,
        },
    }


def _seed_streamer(
    fake_db,
    streamer_id: int,
    name: str,
    *,
    online: bool,
    game_id: int,
    assignments=None,
    priority: int = 1,
):
    fake_db.streamers_by_id[streamer_id] = {
        "streamer_id": streamer_id,
        "streamer_name": name,
        "is_online": online,
        "is_pinned": False,
        "started_at": datetime.now(MSK).isoformat() if online else None,
        "priority": priority,
        "pr_slots": 2,
        "game_id": game_id,
        "game_name": "Grand Theft Auto V" if game_id == 32982 else "Just Chatting",
        "stream_title": "Live",
        "stream_thumbnail_url": "https://img.test/thumb.jpg",
        "profile_image_url": "https://img.test/profile.jpg",
        "added_at": datetime.now(MSK),
        "added_by_id": 10,
        "assignments": assignments or [],
        "assigned_pr_id": None,
    }


async def _client(build_api_app, current_user: dict | None = None):
    app = build_api_app(
        monitoring_router,
        current_user=current_user,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_monitoring_status_aggregates_data(build_api_app, fake_db) -> None:
    _seed_streamer(
        fake_db,
        6001,
        "gta_free",
        online=True,
        game_id=32982,
        assignments=[],
        priority=0,
    )
    _seed_streamer(
        fake_db,
        6002,
        "gta_full",
        online=True,
        game_id=32982,
        assignments=[
            {"pr_id": 1, "is_probation": False},
            {"pr_id": 2, "is_probation": True},
        ],
        priority=2,
    )
    _seed_streamer(
        fake_db,
        6003,
        "chatting",
        online=True,
        game_id=509658,
        assignments=[],
        priority=1,
    )
    _seed_streamer(
        fake_db, 6004, "offline", online=False, game_id=32982, assignments=[]
    )

    async with await _client(
        build_api_app,
        current_user=_developer_user(),
    ) as client:
        response = await client.get("/api/monitoring/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_streamers"] == 3
    assert data["online_count"] == 3
    assert data["gta_count"] == 2
    assert data["available_count"] == 1
    assert data["available_for_claim"][0]["streamer_name"] == "gta_free"
    assert (
        data["online_streamers"][0]["priority"]
        <= data["online_streamers"][1]["priority"]
    )
