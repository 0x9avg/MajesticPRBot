from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from routes.spec import router as spec_router
MSK = timezone(timedelta(hours=3))

pytestmark = pytest.mark.anyio


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
        "added_at": datetime.now(MSK),
        "added_by_id": 10,
        "assignments": [],
        "assigned_pr_id": None,
    }


async def _client(build_api_app, include_broker: bool = True):
    app = build_api_app(spec_router, include_broker=include_broker)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_claim_streamer_success(build_api_app, fake_db, fake_broker) -> None:
    _seed_streamer(fake_db, 3001, "alpha", True)

    async with await _client(build_api_app) as client:
        response = await client.post(
            "/api/spec/claim",
            json={"streamer_id": 3001, "is_probation": False},
        )

    assert response.status_code == 200
    assert fake_db.pr_current_streamer[1001]["streamer_id"] == 3001
    assert any(call[0] == "spec.claimed" for call in fake_broker.calls)


async def test_claim_streamer_validation_errors(build_api_app, fake_db) -> None:
    _seed_streamer(fake_db, 3001, "already_assigned_target", True)
    _seed_streamer(fake_db, 3002, "offline", False)
    _seed_streamer(fake_db, 3003, "occupied", True)
    fake_db.streamers_by_id[3003]["assignments"] = [
        {"pr_id": 500, "nickname": "user500", "is_probation": False}
    ]
    fake_db.pr_current_streamer[1001] = {
        "streamer_id": 3003,
        "streamer_name": "occupied",
        "assigned_at": datetime.now(MSK),
    }

    async with await _client(build_api_app) as client:
        missing = await client.post(
            "/api/spec/claim",
            json={"streamer_id": 9999, "is_probation": False},
        )
        offline = await client.post(
            "/api/spec/claim",
            json={"streamer_id": 3002, "is_probation": False},
        )
        already_assigned = await client.post(
            "/api/spec/claim",
            json={"streamer_id": 3001, "is_probation": False},
        )
        slot_taken = await client.post(
            "/api/spec/claim",
            json={"streamer_id": 3003, "is_probation": False},
        )

    assert missing.status_code == 404
    assert offline.status_code == 400
    assert already_assigned.status_code == 409
    assert slot_taken.status_code == 409


async def test_unclaim_streamer_success_and_errors(
    build_api_app, fake_db, fake_broker
) -> None:
    _seed_streamer(fake_db, 3004, "to_unclaim", True)
    fake_db.streamers_by_id[3004]["assignments"] = [
        {"pr_id": 1001, "nickname": "creator", "is_probation": False}
    ]
    fake_db.pr_current_streamer[1001] = {
        "streamer_id": 3004,
        "streamer_name": "to_unclaim",
        "assigned_at": datetime.now(MSK),
    }

    async with await _client(build_api_app) as client:
        missing_streamer = await client.post(
            "/api/spec/unclaim",
            json={"streamer_id": 9999, "reason": "manual_unclaim"},
        )
        ok = await client.post(
            "/api/spec/unclaim",
            json={"streamer_id": 3004, "reason": "manual_unclaim"},
        )
        second_try = await client.post(
            "/api/spec/unclaim",
            json={"streamer_id": 3004, "reason": "manual_unclaim"},
        )

    assert missing_streamer.status_code == 404
    assert ok.status_code == 200
    assert second_try.status_code == 400
    assert any(call[0] == "spec.unclaimed" for call in fake_broker.calls)



async def test_get_pr_sessions_and_assignments(build_api_app, fake_db) -> None:
    fake_db.pr_sessions[901] = [
        {
            "id": 1,
            "pr_id": 901,
            "streamer_id": 555,
            "started_at": datetime.now(MSK),
            "ended_at": datetime.now(MSK),
            "duration_seconds": 60,
            "end_reason": "manual_unclaim",
        }
    ]
    fake_db.pr_current_streamer[901] = {
        "streamer_id": 555,
        "streamer_name": "tester",
        "assigned_at": datetime.now(MSK),
    }

    async with await _client(build_api_app) as client:
        sessions = await client.get("/api/spec/sessions/901")
        assigned = await client.get("/api/spec/by-pr/901")
        unassigned = await client.get("/api/spec/by-pr/9999")

    assert sessions.status_code == 200
    assert len(sessions.json()["data"]) == 1
    assert assigned.status_code == 200
    assert assigned.json()["data"]["assigned"] is True
    assert unassigned.status_code == 200
    assert unassigned.json()["data"]["assigned"] is False


async def test_get_claimable_streamers_by_role_permissions(
    build_api_app, fake_db
) -> None:
    _seed_streamer(fake_db, 3010, "main_free", True)
    _seed_streamer(fake_db, 3011, "main_taken", True)
    _seed_streamer(fake_db, 3012, "both_taken", True)

    fake_db.streamers_by_id[3011]["assignments"] = [
        {"pr_id": 4001, "is_probation": False}
    ]
    fake_db.streamers_by_id[3012]["assignments"] = [
        {"pr_id": 4002, "is_probation": False},
        {"pr_id": 4003, "is_probation": True},
    ]

    # Employee: probation not allowed, should not see main_taken.
    fake_db.assistants_by_id[6001] = {
        "pr_id": 6001,
        "nickname": "Employee",
        "role": "employee",
        "experience_days": 10,
        "status": "free",
        "total_spec_seconds": 0,
        "session_count": 0,
        "added_at": datetime.now(MSK),
    }

    # Junior: probation allowed, should also see main_taken.
    fake_db.assistants_by_id[6002] = {
        "pr_id": 6002,
        "nickname": "Junior",
        "role": "junior_employee",
        "experience_days": 3,
        "status": "free",
        "total_spec_seconds": 0,
        "session_count": 0,
        "added_at": datetime.now(MSK),
    }

    async with await _client(build_api_app) as client:
        employee_view = await client.get("/api/spec/claimable/6001")
        junior_view = await client.get("/api/spec/claimable/6002")

    assert employee_view.status_code == 200
    employee_ids = {s["streamer_id"] for s in employee_view.json()["data"]["streamers"]}
    assert 3010 in employee_ids
    assert 3011 not in employee_ids
    assert employee_view.json()["data"]["can_spec_probation"] is False

    assert junior_view.status_code == 200
    junior_ids = {s["streamer_id"] for s in junior_view.json()["data"]["streamers"]}
    assert 3010 in junior_ids
    assert 3011 in junior_ids
    assert 3012 not in junior_ids
    assert junior_view.json()["data"]["can_spec_probation"] is True


async def test_service_principal_can_view_pr_assignment_and_claimable_targets(
    build_api_app,
    fake_db,
) -> None:
    _seed_streamer(fake_db, 3020, "delta", True)
    fake_db.assistants_by_id[6003] = {
        "pr_id": 6003,
        "nickname": "ServiceTarget",
        "role": "employee",
        "experience_days": 10,
        "status": "free",
        "total_spec_seconds": 0,
        "session_count": 0,
        "added_at": datetime.now(MSK),
    }
    fake_db.pr_current_streamer[6003] = {
        "streamer_id": 3020,
        "streamer_name": "delta",
        "assigned_at": datetime.now(MSK),
    }

    service_principal = {
        "principal_type": "service",
        "service_name": "discord_service",
        "permissions": {
            "spec.sessions.self.view": True,
            "spec.claimable.view": True,
        },
    }

    app = build_api_app(spec_router, current_user=service_principal)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assigned = await client.get("/api/spec/by-pr/6003")
        claimable = await client.get("/api/spec/claimable/6003")

    assert assigned.status_code == 200
    assert assigned.json()["data"]["assigned"] is True
    assert claimable.status_code == 200
    claimable_ids = {item["streamer_id"] for item in claimable.json()["data"]["streamers"]}
    assert 3020 in claimable_ids
