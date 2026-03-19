from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from routes.assistant_weekly import router as assistant_weekly_router

MSK = timezone(timedelta(hours=3))
pytestmark = pytest.mark.anyio


def _seed_assistant(
    fake_db,
    pr_id: int,
    *,
    nickname: str = "Assistant",
    role: str = "employee",
    appointed_at: datetime | None = None,
    dismissed_at: datetime | None = None,
) -> None:
    now = appointed_at or datetime(2026, 3, 10, 12, 0, tzinfo=MSK)
    fake_db.assistants_by_id[pr_id] = {
        "pr_id": pr_id,
        "nickname": nickname,
        "role": role,
        "experience_days": 42,
        "status": "free",
        "assigned_to_type": None,
        "assigned_to_id": None,
        "assigned_to_name": None,
        "total_spec_seconds": 0,
        "session_count": 0,
        "added_at": now,
        "appointed_at": now,
        "dismissed_at": dismissed_at,
        "gross_points": 0.0,
        "net_points": 0.0,
        "active_point_penalty": 0.0,
        "active_percent_penalty": 0.0,
        "active_checks": 0.0,
        "active_warning_units": 0,
        "active_strict_warnings": 0,
        "active_oral_warnings": 0,
        "active_warnings_display": "0/2 0/2",
    }


def _seed_active_week(fake_db, assistant_id: int, week_start: date) -> None:
    fake_db.current_sanction_policy.update(
        {
            "daily_norm_spec": 4.0,
            "daily_norm_mchat": 1,
            "daily_norm_complaints": 1,
        }
    )
    for offset in range(7):
        work_date = (week_start + timedelta(days=offset)).isoformat()
        fake_db.assistant_day_spec_hours[(assistant_id, work_date)] = 4.0
        fake_db.assistant_day_mchat[(assistant_id, work_date)] = 1
        fake_db.assistant_day_complaints[(assistant_id, work_date)] = 1


async def _client(build_api_app, current_user: dict | None = None):
    app = build_api_app(assistant_weekly_router, current_user=current_user)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_current_weekly_stats_resolves_manual_override(
    build_api_app,
    fake_db,
) -> None:
    week_start = date(2026, 3, 16)
    fake_db.weekly_today = date(2026, 3, 19)
    _seed_assistant(fake_db, 1001, nickname="Alice")
    _seed_active_week(fake_db, 1001, week_start)

    monday = week_start.isoformat()
    fake_db.assistant_day_spec_hours[(1001, monday)] = 0.0
    fake_db.assistant_day_mchat[(1001, monday)] = 0
    fake_db.assistant_day_complaints[(1001, monday)] = 0
    fake_db.assistant_day_status_overrides[(1001, monday)] = {
        "manual_status": "U",
        "updated_at": datetime(2026, 3, 19, 10, 0, tzinfo=MSK),
        "updated_by_id": 1,
    }

    async with await _client(build_api_app) as client:
        response = await client.get("/api/assistant-weekly/current")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["week_start"] == "2026-03-16"
    assert payload["week_end"] == "2026-03-22"
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    monday_day = item["days"][0]
    assert monday_day["manual_status"] == "U"
    assert monday_day["auto_status"] == "P"
    assert monday_day["resolved_status"] == "U"
    assert monday_day["status_source"] == "manual"
    assert item["count_U"] == 1


async def test_get_current_weekly_stats_allows_manual_clear_of_auto_absence(
    build_api_app,
    fake_db,
) -> None:
    week_start = date(2026, 3, 16)
    fake_db.weekly_today = date(2026, 3, 19)
    _seed_assistant(fake_db, 1001, nickname="Alice")
    _seed_active_week(fake_db, 1001, week_start)

    monday = week_start.isoformat()
    fake_db.assistant_day_spec_hours[(1001, monday)] = 0.0
    fake_db.assistant_day_mchat[(1001, monday)] = 0
    fake_db.assistant_day_complaints[(1001, monday)] = 0
    fake_db.assistant_day_status_overrides[(1001, monday)] = {
        "manual_status": "NONE",
        "updated_at": datetime(2026, 3, 19, 10, 0, tzinfo=MSK),
        "updated_by_id": 1,
    }

    async with await _client(build_api_app) as client:
        response = await client.get("/api/assistant-weekly/current")

    assert response.status_code == 200
    monday_day = response.json()["data"]["items"][0]["days"][0]
    assert monday_day["manual_status"] is None
    assert monday_day["auto_status"] == "P"
    assert monday_day["resolved_status"] is None
    assert monday_day["status_source"] == "manual"


async def test_admin_overview_normalizes_week_start_and_exposes_options(
    build_api_app,
    fake_db,
) -> None:
    week_start = date(2026, 3, 16)
    fake_db.weekly_today = date(2026, 3, 19)
    _seed_assistant(fake_db, 1001, nickname="Alice")
    _seed_active_week(fake_db, 1001, week_start)

    async with await _client(build_api_app) as client:
        response = await client.get("/api/assistant-weekly/admin?week_start=2026-03-19")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["week_start"] == "2026-03-16"
    assert payload["week_end"] == "2026-03-22"
    assert {item["value"] for item in payload["payout_types"]} == {"EXP", "Premium", "MC", "MONEY"}
    assert "RU1" in payload["payout_servers"]
    assert "Отпуск" in payload["result_options"]
    assert payload["items"][0]["payout_issue_status"] == "pending"
    assert payload["items"][0]["payout_issued_at"] is None


async def test_admin_detail_save_round_trip_updates_selected_result_and_command(
    build_api_app,
    fake_db,
) -> None:
    week_start = date(2026, 3, 16)
    fake_db.weekly_today = date(2026, 3, 19)
    _seed_assistant(fake_db, 1001, nickname="Alice", role="employee")
    _seed_active_week(fake_db, 1001, week_start)

    async with await _client(build_api_app) as client:
        save_response = await client.put(
            "/api/assistant-weekly/admin/1001?week_start=2026-03-19",
            json={
                "day_overrides": [
                    {"work_date": "2026-03-17", "manual_status": "O", "is_manual_override": True},
                    {"work_date": "2026-03-18", "manual_status": None, "is_manual_override": False},
                ],
                "selected_result": "Актив",
                "payout_type": "MONEY",
                "payout_server": "RU1",
                "payout_static": "static",
            },
        )
        detail_response = await client.get(
            "/api/assistant-weekly/admin/1001?week_start=2026-03-16"
        )

    assert save_response.status_code == 200
    saved = save_response.json()["data"]
    assert saved["selected_result"] == "Актив"
    assert saved["result_display"] == "Актив"
    assert saved["payout_issue_status"] == "pending"
    assert saved["generated_payout_available"] is True
    assert (
        saved["generated_payout_command"]
        == "RU1:givemoney static 200000 pr-assist_byStynee"
    )
    assert saved["day_overrides"][1]["manual_status"] == "O"
    assert saved["day_overrides"][1]["is_manual_override"] is True

    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["selected_result"] == "Актив"
    assert detail["generated_payout_command"] == saved["generated_payout_command"]


async def test_payout_issue_route_marks_command_ready_row_as_issued_and_logs(
    build_api_app,
    fake_db,
) -> None:
    week_start = date(2026, 3, 16)
    fake_db.weekly_today = date(2026, 3, 19)
    _seed_assistant(fake_db, 1001, nickname="Alice", role="employee")
    _seed_active_week(fake_db, 1001, week_start)
    fake_db.assistant_weekly_reviews[(1001, week_start.isoformat())] = {
        "selected_result": "Актив",
        "payout_type": "MONEY",
        "payout_server": "RU1",
        "payout_static": "static",
        "payout_issue_status": "pending",
        "updated_at": datetime(2026, 3, 19, 10, 0, tzinfo=MSK),
        "updated_by_id": 7,
    }

    async with await _client(build_api_app) as client:
        response = await client.put(
            "/api/assistant-weekly/admin/1001/payout-issue?week_start=2026-03-16",
            json={"status": "issued"},
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["payout_issue_status"] == "issued"
    assert payload["payout_issued_at"] is not None
    assert payload["generated_payout_command"] == "RU1:givemoney static 200000 pr-assist_byStynee"
    assert fake_db.logged_actions[-1]["action"] == "assistant.weekly_payout_issue.update"
    assert fake_db.logged_actions[-1]["details"]["payload"]["from_status"] == "pending"
    assert fake_db.logged_actions[-1]["details"]["payload"]["to_status"] == "issued"


async def test_payout_issue_route_rejects_row_without_ready_command(
    build_api_app,
    fake_db,
) -> None:
    week_start = date(2026, 3, 16)
    fake_db.weekly_today = date(2026, 3, 19)
    _seed_assistant(fake_db, 1001, nickname="Alice", role="employee")
    _seed_active_week(fake_db, 1001, week_start)
    fake_db.assistant_weekly_reviews[(1001, week_start.isoformat())] = {
        "selected_result": "Актив",
        "payout_type": None,
        "payout_server": None,
        "payout_static": None,
        "payout_issue_status": "pending",
        "updated_at": datetime(2026, 3, 19, 10, 0, tzinfo=MSK),
        "updated_by_id": 7,
    }

    async with await _client(build_api_app) as client:
        response = await client.put(
            "/api/assistant-weekly/admin/1001/payout-issue?week_start=2026-03-16",
            json={"status": "issued"},
        )

    assert response.status_code == 400
    assert "Команда недоступна" in response.json()["detail"]


async def test_payout_issue_route_can_clear_issued_status(
    build_api_app,
    fake_db,
) -> None:
    week_start = date(2026, 3, 16)
    fake_db.weekly_today = date(2026, 3, 19)
    _seed_assistant(fake_db, 1001, nickname="Alice", role="employee")
    _seed_active_week(fake_db, 1001, week_start)
    fake_db.assistant_weekly_reviews[(1001, week_start.isoformat())] = {
        "selected_result": "Актив",
        "payout_type": "MONEY",
        "payout_server": "RU1",
        "payout_static": "static",
        "payout_issue_status": "issued",
        "payout_issued_at": datetime(2026, 3, 19, 12, 30, tzinfo=MSK),
        "payout_issued_by_id": 7,
        "updated_at": datetime(2026, 3, 19, 10, 0, tzinfo=MSK),
        "updated_by_id": 7,
    }

    async with await _client(build_api_app) as client:
        response = await client.put(
            "/api/assistant-weekly/admin/1001/payout-issue?week_start=2026-03-16",
            json={"status": "pending"},
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["payout_issue_status"] == "pending"
    assert payload["payout_issued_at"] is None


async def test_admin_save_auto_resets_issued_payout_and_logs_transition(
    build_api_app,
    fake_db,
) -> None:
    week_start = date(2026, 3, 16)
    fake_db.weekly_today = date(2026, 3, 19)
    _seed_assistant(fake_db, 1001, nickname="Alice", role="employee")
    _seed_active_week(fake_db, 1001, week_start)
    fake_db.assistant_weekly_reviews[(1001, week_start.isoformat())] = {
        "selected_result": "Актив",
        "payout_type": "MONEY",
        "payout_server": "RU1",
        "payout_static": "static",
        "payout_issue_status": "issued",
        "payout_issued_at": datetime(2026, 3, 19, 12, 30, tzinfo=MSK),
        "payout_issued_by_id": 7,
        "updated_at": datetime(2026, 3, 19, 10, 0, tzinfo=MSK),
        "updated_by_id": 7,
    }

    async with await _client(build_api_app) as client:
        response = await client.put(
            "/api/assistant-weekly/admin/1001?week_start=2026-03-16",
            json={
                "day_overrides": [],
                "selected_result": "Актив",
                "payout_type": "MONEY",
                "payout_server": "RU2",
                "payout_static": "static",
            },
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["payout_issue_status"] == "pending"
    issue_logs = [
        item for item in fake_db.logged_actions
        if item["action"] == "assistant.weekly_payout_issue.update"
    ]
    assert issue_logs
    assert issue_logs[-1]["details"]["payload"]["auto_reset"] is True
    assert issue_logs[-1]["details"]["payload"]["from_status"] == "issued"
    assert issue_logs[-1]["details"]["payload"]["to_status"] == "pending"


async def test_admin_save_can_suppress_auto_absence_with_manual_empty_override(
    build_api_app,
    fake_db,
) -> None:
    week_start = date(2026, 3, 16)
    fake_db.weekly_today = date(2026, 3, 19)
    _seed_assistant(fake_db, 1001, nickname="Alice", role="employee")
    _seed_active_week(fake_db, 1001, week_start)
    monday = week_start.isoformat()
    fake_db.assistant_day_spec_hours[(1001, monday)] = 0.0
    fake_db.assistant_day_mchat[(1001, monday)] = 0
    fake_db.assistant_day_complaints[(1001, monday)] = 0

    async with await _client(build_api_app) as client:
        save_response = await client.put(
            "/api/assistant-weekly/admin/1001?week_start=2026-03-16",
            json={
                "day_overrides": [
                    {"work_date": "2026-03-16", "manual_status": None, "is_manual_override": True},
                ],
                "selected_result": None,
                "payout_type": None,
                "payout_server": None,
                "payout_static": None,
            },
        )

    assert save_response.status_code == 200
    monday_day = save_response.json()["data"]["days"][0]
    assert monday_day["manual_status"] is None
    assert monday_day["auto_status"] == "P"
    assert monday_day["resolved_status"] is None
    assert monday_day["status_source"] == "manual"


async def test_admin_routes_require_manage_permission(build_api_app) -> None:
    current_user = {
        "id": 2,
        "username": "employee",
        "nickname": "Employee",
        "role": "employee",
        "principal_type": "user",
        "discord_id": 1002,
        "require_password_change": False,
        "permissions": {
            "assistants.weekly.view": True,
        },
    }

    async with await _client(build_api_app, current_user=current_user) as client:
        response = await client.get("/api/assistant-weekly/admin?week_start=2026-03-19")

    assert response.status_code == 403
    assert "assistants.weekly.manage" in response.json()["detail"]
