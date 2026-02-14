from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from routes.assistants import router as assistants_router

pytestmark = pytest.mark.anyio


def _seed_assistant(
    fake_db, pr_id: int, nickname: str = "Assistant", role: str = "employee"
) -> None:
    fake_db.assistants_by_id[pr_id] = {
        "pr_id": pr_id,
        "nickname": nickname,
        "role": role,
        "experience_days": 12,
        "status": "free",
        "assigned_to_type": None,
        "assigned_to_id": None,
        "assigned_to_name": None,
        "total_spec_seconds": 7200,
        "session_count": 5,
        "added_at": datetime.now(timezone.utc),
    }


async def _client(build_api_app):
    app = build_api_app(assistants_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_all_assistants_returns_list(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1001, "Alice")

    async with await _client(build_api_app) as assistants_client:
        response = await assistants_client.get("/api/assistants")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"][0]["nickname"] == "Alice"
    assert payload["data"][0]["total_spec_hours"] == 2.0


async def test_get_assistant_not_found(build_api_app) -> None:
    async with await _client(build_api_app) as assistants_client:
        response = await assistants_client.get("/api/assistants/9999")
    assert response.status_code == 404


async def test_create_assistant_invalid_role(build_api_app) -> None:
    async with await _client(build_api_app) as assistants_client:
        response = await assistants_client.post(
            "/api/assistants",
            json={
                "pr_id": 1200,
                "nickname": "Bad",
                "role": "superadmin",
                "experience_days": 0,
            },
        )
    assert response.status_code == 400
    assert "Invalid role" in response.json()["detail"]


async def test_create_assistant_success(build_api_app, fake_db) -> None:
    async with await _client(build_api_app) as assistants_client:
        response = await assistants_client.post(
            "/api/assistants",
            json={
                "pr_id": 1201,
                "nickname": "Bob",
                "role": "employee",
                "experience_days": 3,
            },
        )
    assert response.status_code == 200
    assert fake_db.assistants_by_id[1201]["nickname"] == "Bob"


async def test_update_assignment_validation_and_success(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1300, "Charlie")

    async with await _client(build_api_app) as assistants_client:
        bad = await assistants_client.put(
            "/api/assistants/1300/assign",
            json={
                "assigned_to_type": "invalid",
                "assigned_to_id": 1,
                "assigned_to_name": "X",
            },
        )
        ok = await assistants_client.put(
            "/api/assistants/1300/assign",
            json={
                "assigned_to_type": "streamer",
                "assigned_to_id": 501,
                "assigned_to_name": "StreamerX",
            },
        )

    assert bad.status_code == 400
    assert ok.status_code == 200
    assert fake_db.assistants_by_id[1300]["assigned_to_name"] == "StreamerX"


async def test_delete_assistant(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1400, "DeleteMe")

    async with await _client(build_api_app) as assistants_client:
        ok = await assistants_client.delete("/api/assistants/1400")
        missing = await assistants_client.delete("/api/assistants/1400")

    assert ok.status_code == 200
    assert 1400 not in fake_db.assistants_by_id
    assert missing.status_code == 404


async def test_get_logs_for_assistant(build_api_app, fake_db) -> None:
    fake_db.assistant_logs_by_id[1001] = [
        {
            "id": 1,
            "action": "Assigned",
            "target": "StreamerAlpha",
            "created_at": "2026-02-14T10:00:00",
        },
        {
            "id": 2,
            "action": "Unassigned (manual_unclaim)",
            "target": "StreamerAlpha",
            "created_at": "2026-02-14T11:30:00",
        },
    ]

    async with await _client(build_api_app) as assistants_client:
        response = await assistants_client.get("/api/assistants/1001/logs")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["data"], list)
    assert payload["data"][0] == {
        "id": 1,
        "action": "Assigned",
        "target": "StreamerAlpha",
        "created_at": "2026-02-14T10:00:00",
    }


async def test_get_capabilities_for_unknown_and_known_assistant(
    build_api_app, fake_db
) -> None:
    async with await _client(build_api_app) as assistants_client:
        unknown = await assistants_client.get("/api/assistants/777/capabilities")

    assert unknown.status_code == 200
    assert unknown.json()["data"]["can_view_dashboard"] is False

    _seed_assistant(fake_db, 1500, "Dev", role="developer")
    async with await _client(build_api_app) as assistants_client:
        known = await assistants_client.get("/api/assistants/1500/capabilities")

    assert known.status_code == 200
    assert known.json()["data"]["can_register_users"] is True


async def test_reset_and_manual_session(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1600, "ResetUser")

    async with await _client(build_api_app) as assistants_client:
        reset_response = await assistants_client.post("/api/assistants/1600/reset")
        session_response = await assistants_client.post(
            "/api/assistants/1600/session",
            json={
                "target_type": "streamer",
                "target_id": 5001,
                "target_name": "StreamerY",
                "duration_seconds": 3600,
                "date": "2026-02-14",
                "is_probation": False,
                "priority": 2,
                "admin_id": 9999,
            },
        )

    assert reset_response.status_code == 200
    assert fake_db.assistants_by_id[1600]["total_spec_seconds"] == 0
    assert session_response.status_code == 200
    assert len(fake_db.manual_sessions) == 1


async def test_manual_session_not_found_returns_404(build_api_app) -> None:
    async with await _client(build_api_app) as assistants_client:
        response = await assistants_client.post(
            "/api/assistants/404/session",
            json={
                "target_type": "streamer",
                "target_id": 1,
                "target_name": "Nope",
                "duration_seconds": 600,
                "date": "2026-02-14",
                "is_probation": False,
                "priority": 0,
                "admin_id": 1,
            },
        )

    assert response.status_code == 404
