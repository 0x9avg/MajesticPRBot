from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from routes.spec import router as spec_router

pytestmark = pytest.mark.anyio


def _seed_streamer(
    fake_db, streamer_id: int, name: str, is_online: bool = True
) -> None:
    fake_db.streamers_by_id[streamer_id] = {
        "streamer_id": streamer_id,
        "streamer_name": name,
        "is_online": is_online,
        "is_pinned": False,
        "stream_points_override": None,
        "started_at": None,
        "priority": 1,
        "pr_slots": 2,
        "game_id": 32982,
        "game_name": "Grand Theft Auto V",
        "stream_title": "Live",
        "stream_thumbnail_url": "https://img.test/thumb.jpg",
        "profile_image_url": "https://img.test/profile.jpg",
        "added_at": datetime.now(timezone.utc),
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
            json={"streamer_id": 3001, "pr_id": 101, "is_probation": False},
        )

    assert response.status_code == 200
    assert fake_db.pr_current_streamer[101]["streamer_id"] == 3001
    assert any(call[0] == "spec.claimed" for call in fake_broker.calls)


async def test_claim_streamer_validation_errors(build_api_app, fake_db) -> None:
    _seed_streamer(fake_db, 3001, "already_assigned_target", True)
    _seed_streamer(fake_db, 3002, "offline", False)
    _seed_streamer(fake_db, 3003, "occupied", True)
    fake_db.streamers_by_id[3003]["assignments"] = [
        {"pr_id": 500, "nickname": "user500", "is_probation": False}
    ]
    fake_db.pr_current_streamer[999] = {
        "streamer_id": 3003,
        "streamer_name": "occupied",
        "assigned_at": datetime.now(timezone.utc),
    }

    async with await _client(build_api_app) as client:
        missing = await client.post(
            "/api/spec/claim",
            json={"streamer_id": 9999, "pr_id": 1, "is_probation": False},
        )
        offline = await client.post(
            "/api/spec/claim",
            json={"streamer_id": 3002, "pr_id": 1, "is_probation": False},
        )
        already_assigned = await client.post(
            "/api/spec/claim",
            json={"streamer_id": 3001, "pr_id": 999, "is_probation": False},
        )
        slot_taken = await client.post(
            "/api/spec/claim",
            json={"streamer_id": 3003, "pr_id": 123, "is_probation": False},
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
        {"pr_id": 111, "nickname": "user111", "is_probation": False}
    ]
    fake_db.pr_current_streamer[111] = {
        "streamer_id": 3004,
        "streamer_name": "to_unclaim",
        "assigned_at": datetime.now(timezone.utc),
    }

    async with await _client(build_api_app) as client:
        missing_streamer = await client.post(
            "/api/spec/unclaim",
            json={"streamer_id": 9999, "pr_id": 111, "reason": "manual"},
        )
        bad_pr = await client.post(
            "/api/spec/unclaim",
            json={"streamer_id": 3004, "pr_id": 5555, "reason": "manual"},
        )
        ok = await client.post(
            "/api/spec/unclaim",
            json={"streamer_id": 3004, "pr_id": 111, "reason": "manual"},
        )

    assert missing_streamer.status_code == 404
    assert bad_pr.status_code == 400
    assert ok.status_code == 200
    assert any(call[0] == "spec.unclaimed" for call in fake_broker.calls)


async def test_transfer_streamer_success_and_conflicts(
    build_api_app, fake_db, fake_broker
) -> None:
    _seed_streamer(fake_db, 3005, "source", True)
    fake_db.streamers_by_id[3005]["assignments"] = [
        {"pr_id": 201, "nickname": "u201", "is_probation": False}
    ]
    fake_db.pr_current_streamer[201] = {
        "streamer_id": 3005,
        "streamer_name": "source",
        "assigned_at": datetime.now(timezone.utc),
    }
    fake_db.pr_current_streamer[202] = {
        "streamer_id": 3999,
        "streamer_name": "busy",
        "assigned_at": datetime.now(timezone.utc),
    }

    async with await _client(build_api_app) as client:
        target_busy = await client.post(
            "/api/spec/transfer",
            json={"streamer_id": 3005, "from_pr_id": 201, "to_pr_id": 202},
        )

    assert target_busy.status_code == 409

    fake_db.pr_current_streamer.pop(202, None)

    async with await _client(build_api_app) as client:
        bad_from = await client.post(
            "/api/spec/transfer",
            json={"streamer_id": 3005, "from_pr_id": 999, "to_pr_id": 203},
        )
        ok = await client.post(
            "/api/spec/transfer",
            json={"streamer_id": 3005, "from_pr_id": 201, "to_pr_id": 203},
        )

    assert bad_from.status_code == 400
    assert ok.status_code == 200
    assert fake_db.pr_current_streamer[203]["streamer_id"] == 3005
    assert any(call[0] == "spec.transferred" for call in fake_broker.calls)


async def test_swap_streamers_success_and_errors(
    build_api_app, fake_db, fake_broker
) -> None:
    _seed_streamer(fake_db, 3006, "one", True)
    _seed_streamer(fake_db, 3007, "two", True)

    fake_db.streamers_by_id[3006]["assignments"] = [
        {"pr_id": 301, "nickname": "u301", "is_probation": False}
    ]
    fake_db.streamers_by_id[3007]["assignments"] = [
        {"pr_id": 302, "nickname": "u302", "is_probation": False}
    ]
    fake_db.pr_current_streamer[301] = {
        "streamer_id": 3006,
        "streamer_name": "one",
        "assigned_at": datetime.now(timezone.utc),
    }
    fake_db.pr_current_streamer[302] = {
        "streamer_id": 3007,
        "streamer_name": "two",
        "assigned_at": datetime.now(timezone.utc),
    }

    async with await _client(build_api_app) as client:
        same = await client.post("/api/spec/swap", json={"pr1_id": 301, "pr2_id": 301})
        ok = await client.post("/api/spec/swap", json={"pr1_id": 301, "pr2_id": 302})

    assert same.status_code == 400
    assert ok.status_code == 200
    assert fake_db.pr_current_streamer[301]["streamer_id"] == 3007
    assert fake_db.pr_current_streamer[302]["streamer_id"] == 3006
    assert any(call[0] == "spec.swapped" for call in fake_broker.calls)


async def test_get_pr_sessions_and_assignments(build_api_app, fake_db) -> None:
    fake_db.pr_sessions[901] = [
        {
            "id": 1,
            "pr_id": 901,
            "streamer_id": 555,
            "started_at": datetime.now(timezone.utc),
            "ended_at": datetime.now(timezone.utc),
            "duration_seconds": 60,
            "end_reason": "manual",
        }
    ]
    fake_db.pr_current_streamer[901] = {
        "streamer_id": 555,
        "streamer_name": "tester",
        "assigned_at": datetime.now(timezone.utc),
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
        "added_at": datetime.now(timezone.utc),
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
        "added_at": datetime.now(timezone.utc),
    }

    async with await _client(build_api_app) as client:
        employee_view = await client.get("/api/spec/claimable?user_id=6001")
        junior_view = await client.get("/api/spec/claimable?user_id=6002")

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
