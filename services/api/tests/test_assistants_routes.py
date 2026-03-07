from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from routes.assistants import router as assistants_router
MSK = timezone(timedelta(hours=3))

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
        "added_at": datetime.now(MSK),
        "appointed_at": datetime.now(MSK),
        "auto_points_total": 10.0,
        "manual_points_adjustment": 0.0,
        "total_points": 10.0,
        "penalty_points": 0.0,
        "penalty_percent": 0.0,
        "display_points": 10.0,
        "warnings_units": 0,
        "strict_warnings": 0,
        "oral_warnings": 0,
        "warnings_display": "0/2 0/2",
    }


async def _client(build_api_app, current_user: dict | None = None):
    app = build_api_app(assistants_router, current_user=current_user)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _employee_current_user(discord_id: int = 1001) -> dict:
    return {
        "id": discord_id,
        "username": f"user_{discord_id}",
        "nickname": f"User{discord_id}",
        "role": "employee",
        "principal_type": "user",
        "discord_id": discord_id,
        "require_password_change": False,
        "permissions": {
            "assistants.view": True,
            "logs.pr_actions.view": True,
        },
    }


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
    assert "Невалидная роль" in response.json()["detail"]


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
            "priority": 1.0,
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


async def test_employee_can_view_own_logs(build_api_app, fake_db) -> None:
    fake_db.assistant_logs_by_id[2001] = [
        {
            "id": 1,
            "action": "Assigned",
            "target": "StreamerA",
            "created_at": "2026-02-14T10:00:00",
        }
    ]

    async with await _client(
        build_api_app,
        current_user=_employee_current_user(discord_id=2001),
    ) as assistants_client:
        response = await assistants_client.get("/api/assistants/2001/logs")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["data"], list)
    assert payload["data"][0]["target"] == "StreamerA"


async def test_employee_cannot_view_other_assistant_logs(build_api_app, fake_db) -> None:
    fake_db.assistant_logs_by_id[3001] = [
        {
            "id": 1,
            "action": "Assigned",
            "target": "StreamerB",
            "created_at": "2026-02-14T10:00:00",
        }
    ]

    async with await _client(
        build_api_app,
        current_user=_employee_current_user(discord_id=2001),
    ) as assistants_client:
        response = await assistants_client.get("/api/assistants/3001/logs")

    assert response.status_code == 403


async def test_get_assistant_sessions_admin_only_endpoint(
    build_api_app, fake_db
) -> None:
    _seed_assistant(fake_db, 1002, "SessionAdmin")
    fake_db.assistant_sessions_by_id[1002] = [
        {
            "id": 9001,
            "pr_id": 1002,
            "target_type": "streamer",
            "target_id": "5001",
            "target_name": "StreamerOne",
            "started_at": "2026-02-14T10:00:00",
            "ended_at": "2026-02-14T11:00:00",
            "duration_seconds": 3600,
            "credited_points": 1.0,
            "is_probation": False,
            "priority_auto": 1,
            "priority_override": None,
            "rate_auto": 0.5,
            "rate_override": None,
            "deleted_at": None,
            "delete_reason": None,
        }
    ]

    async with await _client(build_api_app) as assistants_client:
        response = await assistants_client.get("/api/assistants/1002/sessions")

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == "9001"
    assert data[0]["target_name"] == "StreamerOne"


async def test_get_capabilities_for_unknown_and_known_assistant(
    build_api_app, fake_db
) -> None:
    async with await _client(build_api_app) as assistants_client:
        unknown = await assistants_client.get("/api/assistants/777/capabilities")

    assert unknown.status_code == 200
    assert unknown.json()["data"] == {}

    _seed_assistant(fake_db, 1500, "Dev", role="developer")
    async with await _client(build_api_app) as assistants_client:
        known = await assistants_client.get("/api/assistants/1500/capabilities")

    assert known.status_code == 200
    assert known.json()["data"]["admin.users.create"] is True


async def test_manual_session(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1600, "ResetUser")

    async with await _client(build_api_app) as assistants_client:
        session_response = await assistants_client.post(
            "/api/assistants/1600/session",
            json={
                "target_type": "streamer",
                "target_id": 5001,
                "target_name": "StreamerY",
                "started_at": "2026-02-14T10:00:00Z",
                "ended_at": "2026-02-14T11:00:00Z",
                "is_probation": False,
                "priority": 2,
            },
        )

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
                "started_at": "2026-02-14T10:00:00Z",
                "ended_at": "2026-02-14T10:10:00Z",
                "is_probation": False,
                "priority": 0,
            },
        )

    assert response.status_code == 404


async def test_adjust_points_sanctions_and_warnings_endpoints(
    build_api_app, fake_db
) -> None:
    _seed_assistant(fake_db, 1700, "PenaltyUser")

    async with await _client(build_api_app) as assistants_client:
        adjust = await assistants_client.post(
            "/api/assistants/1700/points/adjust",
            json={"delta": 3.25},
        )
        sanctions = await assistants_client.patch(
            "/api/assistants/1700/sanctions",
            json={"penalty_points": 1.5, "penalty_percent": 10},
        )
        warnings = await assistants_client.post(
            "/api/assistants/1700/warnings",
            json={"oral_delta": 2, "strict_delta": 0},
        )

    assert adjust.status_code == 200
    assert sanctions.status_code == 200
    assert warnings.status_code == 200
    assert fake_db.assistants_by_id[1700]["manual_points_adjustment"] == 3.25
    assert fake_db.assistants_by_id[1700]["penalty_points"] == 1.5
    assert fake_db.assistants_by_id[1700]["warnings_units"] == 2
    assert len(fake_db.logged_actions) >= 3


async def test_admin_session_patch_and_delete_routes(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1800, "SessionUser")

    async with await _client(build_api_app) as assistants_client:
        patch_resp = await assistants_client.patch(
            "/api/assistants/1800/sessions/9001",
            json={
                "target_type": "manual",
                "target_id": None,
                "started_at": "2026-02-14T12:00:00Z",
                "ended_at": "2026-02-14T13:00:00Z",
                "priority_override": 2,
            },
        )
        delete_resp = await assistants_client.delete(
            "/api/assistants/1800/sessions/9001",
        )

    assert patch_resp.status_code == 200
    assert delete_resp.status_code == 200


async def test_non_admin_cannot_use_sensitive_assistant_endpoints(
    build_api_app, fake_db
) -> None:
    _seed_assistant(fake_db, 1900, "NoAdmin")
    app = build_api_app(
        assistants_router,
        current_user={
            "id": 2,
            "username": "employee",
            "nickname": "Employee",
            "role": "employee",
            "discord_id": 1900,
            "require_password_change": False,
            "permissions": {},
        },
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as assistants_client:
        adjust = await assistants_client.post(
            "/api/assistants/1900/points/adjust",
            json={"delta": 1.0},
        )
        sessions = await assistants_client.get("/api/assistants/1900/sessions")
        manual_session = await assistants_client.post(
            "/api/assistants/1900/session",
            json={
                "target_type": "streamer",
                "target_id": 5001,
                "target_name": "StreamerY",
                "started_at": "2026-02-14T10:00:00Z",
                "ended_at": "2026-02-14T11:00:00Z",
                "is_probation": False,
                "priority": 1,
            },
        )

    assert adjust.status_code == 403
    assert sessions.status_code == 403
    assert manual_session.status_code == 403


async def test_manual_session_validation_rules(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1910, "ValidationUser")
    async with await _client(build_api_app) as assistants_client:
        # Manual without comment should now succeed (comment no longer required)
        manual_without_comment = await assistants_client.post(
            "/api/assistants/1910/session",
            json={
                "target_type": "manual",
                "target_id": None,
                "started_at": "2026-02-14T10:00:00Z",
                "ended_at": "2026-02-14T11:00:00Z",
            },
        )
        # Manual with target_id should still fail
        manual_with_target = await assistants_client.post(
            "/api/assistants/1910/session",
            json={
                "target_type": "manual",
                "target_id": 5001,
                "started_at": "2026-02-14T10:00:00Z",
                "ended_at": "2026-02-14T11:00:00Z",
            },
        )
        # Streamer without target_id should still fail
        streamer_without_target = await assistants_client.post(
            "/api/assistants/1910/session",
            json={
                "target_type": "streamer",
                "target_id": None,
                "started_at": "2026-02-14T10:00:00Z",
                "ended_at": "2026-02-14T11:00:00Z",
            },
        )

    assert manual_without_comment.status_code == 200
    assert manual_with_target.status_code in {400, 422}
    assert streamer_without_target.status_code in {400, 422}
