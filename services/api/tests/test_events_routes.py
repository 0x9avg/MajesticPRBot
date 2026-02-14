from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from routes.events import router as events_router

pytestmark = pytest.mark.anyio


async def _client(build_api_app):
    app = build_api_app(events_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create_sample_event(build_api_app, name: str = "Raid Night") -> dict:
    async with await _client(build_api_app) as client:
        response = await client.post(
            "/api/events",
            json={
                "name": name,
                "description": "Community activity",
                "required_pr_count": 2,
                "priority": 2,
                "pr_slots": 2,
                "is_pinned": False,
                "start_time": None,
                "channel_id": 123456,
                "created_by": 999,
            },
        )
    return response.json()


async def test_create_event_success(build_api_app, fake_db) -> None:
    result = await _create_sample_event(build_api_app)

    assert result["status"] == "success"
    assert result["data"]["id"] == 1
    assert fake_db.events_by_id[1]["name"] == "Raid Night"


async def test_create_event_failure_returns_500(build_api_app, fake_db) -> None:
    fake_db.force_create_event_fail = True

    async with await _client(build_api_app) as client:
        response = await client.post(
            "/api/events",
            json={
                "name": "Broken",
                "description": "No DB",
                "required_pr_count": 1,
                "priority": 1,
                "pr_slots": 1,
                "is_pinned": False,
                "start_time": None,
                "channel_id": 123,
                "created_by": 1,
            },
        )

    assert response.status_code == 500


async def test_get_active_and_scheduled_events(build_api_app, fake_db) -> None:
    await _create_sample_event(build_api_app, name="Immediate")

    # Scheduled event: start_time set and notification_sent False
    event_id = fake_db.next_event_id
    fake_db.events_by_id[event_id] = {
        "id": event_id,
        "name": "Scheduled",
        "description": "Starts later",
        "required_pr_count": 1,
        "pr_slots": 1,
        "priority": 0,
        "is_pinned": False,
        "start_time": datetime.now(timezone.utc) + timedelta(hours=1),
        "channel_id": 100,
        "created_by": 1,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "notification_sent": False,
        "message_id": 0,
    }
    fake_db.event_participants[event_id] = {}

    async with await _client(build_api_app) as client:
        active = await client.get("/api/events/active")
        scheduled = await client.get("/api/events/scheduled")

    assert active.status_code == 200
    assert len(active.json()["data"]) >= 2
    assert scheduled.status_code == 200
    names = {event["name"] for event in scheduled.json()["data"]}
    assert "Scheduled" in names


async def test_get_event_and_participants(build_api_app, fake_db) -> None:
    await _create_sample_event(build_api_app, name="Lookup")
    fake_db.event_participants[1][42] = datetime.now(timezone.utc)

    async with await _client(build_api_app) as client:
        found = await client.get("/api/events/1")
        missing = await client.get("/api/events/999")
        participants = await client.get("/api/events/1/participants")

    assert found.status_code == 200
    assert found.json()["data"]["name"] == "Lookup"
    assert missing.status_code == 404
    assert participants.status_code == 200
    assert participants.json()["data"][0]["pr_id"] == 42


async def test_join_leave_and_end_event(build_api_app, fake_db) -> None:
    await _create_sample_event(build_api_app, name="Joinable")

    async with await _client(build_api_app) as client:
        join_ok = await client.post("/api/events/1/join", json={"user_id": 500})
        join_dupe = await client.post("/api/events/1/join", json={"user_id": 500})
        leave = await client.post("/api/events/1/leave", json={"user_id": 500})

        # Rejoin two users then end
        await client.post("/api/events/1/join", json={"user_id": 501})
        await client.post("/api/events/1/join", json={"user_id": 502})
        ended = await client.post("/api/events/1/end")

    assert join_ok.status_code == 200
    assert join_dupe.status_code == 400
    assert leave.status_code == 200
    assert ended.status_code == 200
    assert fake_db.events_by_id[1]["is_active"] is False
    assert len(ended.json()["data"]["participants"]) == 2


async def test_update_event_success_and_not_found(build_api_app) -> None:
    await _create_sample_event(build_api_app, name="Editable")

    async with await _client(build_api_app) as client:
        updated = await client.patch(
            "/api/events/1",
            json={"name": "Edited", "priority": 3, "is_pinned": True},
        )
        missing = await client.patch(
            "/api/events/999",
            json={"name": "Nope"},
        )

    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Edited"
    assert updated.json()["data"]["priority"] == 3
    assert missing.status_code == 404


async def test_mark_notification_sent_and_update_message(
    build_api_app, fake_db
) -> None:
    await _create_sample_event(build_api_app, name="Notify")

    async with await _client(build_api_app) as client:
        mark = await client.patch("/api/events/1/notification-sent")
        message = await client.patch("/api/events/1/message?message_id=777")

    assert mark.status_code == 200
    assert message.status_code == 200
    assert fake_db.events_by_id[1]["notification_sent"] is True
    assert fake_db.events_by_id[1]["message_id"] == 777
