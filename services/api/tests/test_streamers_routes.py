from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from routes.streamers import router as streamers_router
MSK = timezone(timedelta(hours=3))

pytestmark = pytest.mark.anyio


def _service_principal_create_streamers() -> dict:
    return {
        "principal_type": "service",
        "service_name": "discord_service",
        "permissions": {"media.create": True},
    }


def _status_sync_user() -> dict:
    return {
        "id": 77,
        "username": "sync-bot",
        "nickname": "SyncBot",
        "role": "developer",
        "principal_type": "user",
        "discord_id": 7077,
        "require_password_change": False,
        "permissions": {
            "media.status.update": True,
        },
    }


def _seed_streamer(
    fake_db, streamer_id: int, name: str, is_online: bool = True
) -> None:
    fake_db.streamers_by_id[streamer_id] = {
        "streamer_id": streamer_id,
        "streamer_name": name,
        "is_online": is_online,
        "is_pinned": False,
        "started_at": None,
        "priority": 1,
        "pr_slots": 2,
        "game_id": 32982,
        "game_name": "Grand Theft Auto V",
        "stream_title": "Live",
        "stream_thumbnail_url": "https://img.test/thumb.jpg",
        "profile_image_url": "https://img.test/profile.jpg",
        "current_stream_priority_override": None,
        "current_stream_pr_slots_override": None,
        "added_at": datetime.now(MSK),
        "added_by_id": 10,
        "assignments": [],
        "assigned_pr_id": None,
    }


async def _client(
    build_api_app,
    include_broker: bool = True,
    current_user: dict | None = None,
):
    app = build_api_app(
        streamers_router,
        include_broker=include_broker,
        current_user=current_user,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_list_streamers_with_online_filter(build_api_app, fake_db) -> None:
    _seed_streamer(fake_db, 2001, "online_streamer", True)
    _seed_streamer(fake_db, 2002, "offline_streamer", False)

    async with await _client(build_api_app) as streamers_client:
        all_response = await streamers_client.get("/api/streamers")
        online_response = await streamers_client.get("/api/streamers?online_only=true")

    assert all_response.status_code == 200
    assert all_response.json()["data"]["total"] == 2
    first_streamer = all_response.json()["data"]["streamers"][0]
    assert "current_stream_priority_override" in first_streamer
    assert "current_stream_pr_slots_override" in first_streamer
    assert "priority_override" not in first_streamer
    assert "pr_slots_override" not in first_streamer
    assert online_response.status_code == 200
    assert online_response.json()["data"]["total"] == 1


async def test_get_streamer_found_and_not_found(build_api_app, fake_db) -> None:
    _seed_streamer(fake_db, 2003, "target_streamer", True)

    async with await _client(build_api_app) as streamers_client:
        found = await streamers_client.get("/api/streamers/2003")
        missing = await streamers_client.get("/api/streamers/99999")

    assert found.status_code == 200
    assert found.json()["data"]["streamer_name"] == "target_streamer"
    assert "priority_override" not in found.json()["data"]
    assert "pr_slots_override" not in found.json()["data"]
    assert missing.status_code == 404


async def test_create_streamer_full_mode_success(
    build_api_app, fake_db, fake_broker
) -> None:
    async with await _client(build_api_app) as streamers_client:
        response = await streamers_client.post(
            "/api/streamers",
            json={
                "streamer_id": 2100,
                "streamer_name": "full_mode_streamer",
                "is_online": True,
                "priority": 2,
                "pr_slots": 2,
            },
        )

    assert response.status_code == 201
    assert fake_db.streamers_by_id[2100]["streamer_name"] == "full_mode_streamer"
    assert fake_db.streamers_by_id[2100]["added_by_id"] == 1001
    assert any(call[0] == "streamer.added" for call in fake_broker.calls)


async def test_create_streamer_rejects_added_by_id_spoof(build_api_app) -> None:
    async with await _client(build_api_app) as streamers_client:
        response = await streamers_client.post(
            "/api/streamers",
            json={
                "streamer_id": 2101,
                "streamer_name": "spoof_streamer",
                "is_online": True,
                "priority": 1,
                "pr_slots": 1,
                "added_by_id": 999999,
            },
        )

    assert response.status_code == 422


async def test_create_streamer_service_actor_uses_system_id(build_api_app, fake_db) -> None:
    async with await _client(
        build_api_app,
        current_user=_service_principal_create_streamers(),
    ) as streamers_client:
        response = await streamers_client.post(
            "/api/streamers",
            json={
                "streamer_id": 2102,
                "streamer_name": "service_streamer",
                "is_online": False,
                "priority": 0,
                "pr_slots": 1,
            },
        )

    assert response.status_code == 201
    assert fake_db.streamers_by_id[2102]["added_by_id"] == 0


async def test_create_streamer_url_mode_pending_or_unavailable(
    build_api_app, fake_broker
) -> None:
    async with await _client(build_api_app) as streamers_client:
        pending = await streamers_client.post(
            "/api/streamers",
            json={
                "twitch_url": "https://twitch.tv/SomeStreamer",
                "priority": 0,
                "pr_slots": 1,
            },
        )

    assert pending.status_code == 202
    assert any(call[0] == "streamer.verify" for call in fake_broker.calls)

    async with await _client(
        build_api_app, include_broker=False
    ) as streamers_client_no_broker:
        unavailable = await streamers_client_no_broker.post(
            "/api/streamers",
            json={
                "twitch_url": "https://twitch.tv/SomeStreamer",
                "priority": 0,
                "pr_slots": 1,
            },
        )

    assert unavailable.status_code == 503


async def test_update_streamer_not_found(build_api_app) -> None:
    async with await _client(build_api_app) as streamers_client:
        response = await streamers_client.patch(
            "/api/streamers/99999",
            json={"priority": 2, "pr_slots": 2},
        )
    assert response.status_code == 404


async def test_update_streamer_success_logs_admin_action(
    build_api_app, fake_db
) -> None:
    _seed_streamer(fake_db, 2200, "to_update", True)

    async with await _client(build_api_app) as streamers_client:
        response = await streamers_client.patch(
            "/api/streamers/2200",
            json={
                "priority": 3,
                "pr_slots": 3,
                "is_pinned": True,
                "current_stream_priority_override": 2,
                "current_stream_pr_slots_override": 4,
            },
        )

    assert response.status_code == 200
    assert fake_db.streamers_by_id[2200]["priority"] == 3
    assert fake_db.streamers_by_id[2200]["pr_slots"] == 3
    assert fake_db.streamers_by_id[2200]["is_pinned"] is True
    assert fake_db.streamers_by_id[2200]["current_stream_priority_override"] == 2
    assert fake_db.streamers_by_id[2200]["current_stream_pr_slots_override"] == 4
    assert len(fake_db.logged_actions) >= 1


async def test_remove_streamer(build_api_app, fake_db) -> None:
    _seed_streamer(fake_db, 2300, "to_delete", True)

    async with await _client(build_api_app) as streamers_client:
        ok = await streamers_client.delete("/api/streamers/2300")
        missing = await streamers_client.delete("/api/streamers/2300")

    assert ok.status_code == 200
    assert 2300 not in fake_db.streamers_by_id
    assert missing.status_code == 404


async def test_update_streamer_status_not_found(build_api_app) -> None:
    async with await _client(
        build_api_app,
        current_user=_status_sync_user(),
    ) as streamers_client:
        response = await streamers_client.patch(
            "/api/streamers/5555/status",
            json={"is_online": True, "game_id": 32982, "game_name": "GTA"},
        )
    assert response.status_code == 404


async def test_update_streamer_status_offline_triggers_auto_unassign(
    build_api_app, fake_db, fake_broker
) -> None:
    _seed_streamer(fake_db, 2400, "status_streamer", True)
    fake_db.streamers_by_id[2400]["assignments"] = [
        {"pr_id": 7001, "nickname": "Worker", "is_probation": False}
    ]
    fake_db.pr_current_streamer[7001] = {
        "streamer_id": 2400,
        "streamer_name": "status_streamer",
        "assigned_at": datetime.now(MSK),
    }

    async with await _client(
        build_api_app,
        current_user=_status_sync_user(),
    ) as streamers_client:
        response = await streamers_client.patch(
            "/api/streamers/2400/status",
            json={
                "is_online": False,
                "game_id": 32982,
                "game_name": "Grand Theft Auto V",
            },
        )

    assert response.status_code == 200
    assert fake_db.streamers_by_id[2400]["is_online"] is False
    assert any(call[0] == "spec.unclaimed" for call in fake_broker.calls)
    assert any(call[0] == "stream.state.offline" for call in fake_broker.calls)


async def test_update_streamer_status_category_change_event(
    build_api_app, fake_db, fake_broker
) -> None:
    _seed_streamer(fake_db, 2401, "category_streamer", True)
    fake_db.streamers_by_id[2401]["game_id"] = 32982

    async with await _client(
        build_api_app,
        current_user=_status_sync_user(),
    ) as streamers_client:
        response = await streamers_client.patch(
            "/api/streamers/2401/status",
            json={"is_online": True, "game_id": 509658, "game_name": "Just Chatting"},
        )

    assert response.status_code == 200
    assert any(call[0] == "stream.state.category" for call in fake_broker.calls)


async def test_sync_status_bulk(build_api_app, fake_db) -> None:
    _seed_streamer(fake_db, 2501, "sync_one", False)
    _seed_streamer(fake_db, 2502, "sync_two", False)

    async with await _client(
        build_api_app,
        current_user=_status_sync_user(),
    ) as streamers_client:
        response = await streamers_client.post(
            "/api/streamers/sync_status",
            json=[
                {
                    "streamer_id": 2501,
                    "is_online": True,
                    "game_id": "32982",
                    "game_name": "GTA",
                },
                {
                    "streamer_id": 2502,
                    "is_online": True,
                    "game_id": "",
                    "game_name": "Just Chatting",
                },
                {"is_online": True},
            ],
        )

    assert response.status_code == 200
    assert response.json()["data"]["updated_count"] == 2


async def test_sync_status_empty_payload(build_api_app) -> None:
    async with await _client(
        build_api_app,
        current_user=_status_sync_user(),
    ) as streamers_client:
        response = await streamers_client.post("/api/streamers/sync_status", json=[])

    assert response.status_code == 200
    assert response.json()["updated_count"] == 0
