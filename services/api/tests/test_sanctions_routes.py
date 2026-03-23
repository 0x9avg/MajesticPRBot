from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from routes.sanctions import router as sanctions_router

MSK = timezone(timedelta(hours=3))
pytestmark = pytest.mark.anyio


def _seed_assistant(fake_db, pr_id: int, nickname: str = "Assistant") -> None:
    fake_db.assistants_by_id[pr_id] = {
        "pr_id": pr_id,
        "nickname": nickname,
        "role": "employee",
        "experience_days": 10,
        "status": "free",
        "assigned_to_type": None,
        "assigned_to_id": None,
        "assigned_to_name": None,
        "total_spec_seconds": 0,
        "session_count": 0,
        "added_at": datetime.now(MSK),
        "appointed_at": datetime.now(MSK),
        "gross_points": 0.0,
        "net_points": 0.0,
        "active_point_penalty": 0.0,
        "active_percent_penalty": 0.0,
        "active_checks": 0.0,
        "active_strict_warnings": 0,
        "active_oral_warnings": 0,
    }


async def test_sanctions_summary_exposes_only_canonical_warning_fields(
    build_api_app,
    fake_db,
) -> None:
    _seed_assistant(fake_db, 1001, "Tester")
    fake_db.assistant_sanctions[1] = {
        "sanction_id": "1",
        "assistant_id": "1001",
        "kind": "strict",
        "amount_total": 1,
        "relieved_amount": 0,
        "active_amount": 1,
        "issued_at": "2026-03-10T09:00:00",
        "source_type": "manual",
        "workoff_items": [],
    }
    fake_db.assistant_sanctions[2] = {
        "sanction_id": "2",
        "assistant_id": "1001",
        "kind": "oral",
        "amount_total": 1,
        "relieved_amount": 0,
        "active_amount": 1,
        "issued_at": "2026-03-11T09:00:00",
        "source_type": "manual",
        "workoff_items": [],
    }

    async with await _client(build_api_app) as client:
        response = await client.get("/api/assistants/1001/sanctions/summary")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["strict"] == 1.0
    assert payload["oral"] == 1.0
    assert "warnings_units" not in payload
    assert "strict_warnings" not in payload
    assert "oral_warnings" not in payload
    assert "warnings_display" not in payload


async def _client(
    build_api_app,
    current_user: dict | None = None,
    *,
    include_broker: bool = True,
):
    app = build_api_app(
        sanctions_router,
        current_user=current_user,
        include_broker=include_broker,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_sanction_routes_require_exact_permission(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1001, "Tester")
    app = build_api_app(
        sanctions_router,
        current_user={
            "id": 2,
            "username": "employee",
            "nickname": "Employee",
            "role": "employee",
            "principal_type": "user",
            "discord_id": 1001,
            "require_password_change": False,
            "permissions": {"assistants.view": True},
        },
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/assistant-sanctions",
            json={"assistant_id": 1001, "kind": "point", "amount": 1},
        )

    assert response.status_code == 403
    assert "assistants.sanctions.manage" in response.json()["detail"]


async def test_day_points_flow_uses_day_status(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1001, "Tester")

    async with await _client(build_api_app) as client:
        save = await client.post(
            "/api/assistant-day-points",
            json={
                "assistant_id": 1001,
                "work_date": "2026-03-15",
                "delta_points": 2.5,
            },
        )
        save_mchat = await client.put(
            "/api/assistant-day-mchat",
            json={
                "assistant_id": 1001,
                "work_date": "2026-03-15",
                "mchat_count": 4,
            },
        )
        status = await client.get("/api/assistants/1001/day-status?date=2026-03-15")

    assert save.status_code == 200
    assert save.json()["data"]["delta_points"] == 2.5
    assert save_mchat.status_code == 200
    assert save_mchat.json()["data"]["mchat_count"] == 4
    assert status.status_code == 200
    assert status.json()["data"]["manual_points_delta"] == 2.5
    assert status.json()["data"]["mchat_count"] == 4


async def test_manual_sanction_relief_replace_and_progress(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1001, "Tester")

    async with await _client(build_api_app) as client:
        created = await client.post(
            "/api/assistant-sanctions",
            json={
                "assistant_id": 1001,
                "kind": "point",
                "amount": 3,
                "workoff_items": [
                    {
                        "metric": "spec",
                        "multiplier": 2,
                        "period_start": "2026-03-01",
                        "period_end": "2026-03-31",
                    }
                ],
            },
        )
        sanction_id = created.json()["data"]["sanction_id"]
        active_before = await client.get("/api/assistants/1001/sanctions/active")
        relief = await client.post(
            f"/api/assistant-sanctions/{sanction_id}/reliefs",
            json={"amount": 1, "relief_type": "manual"},
        )
        replaced = await client.post(
            f"/api/assistant-sanctions/{sanction_id}/replace",
            json={
                "new_kind": "percent",
                "new_amount": 5,
                "basis_date": "2026-03-16",
                "workoff_items": [],
            },
        )
        progress = await client.get(f"/api/sanctions/{sanction_id}/workoff-progress")

    assert created.status_code == 200
    assert active_before.status_code == 200
    assert active_before.json()["data"][0]["assistant_id"] == "1001"
    assert relief.status_code == 200
    assert relief.json()["data"]["active_amount"] == 2
    assert replaced.status_code == 200
    assert replaced.json()["data"]["kind"] == "percent"
    assert replaced.json()["data"]["active_amount"] == 5
    assert progress.status_code == 200
    assert progress.json()["data"]["assistant_id"] == "1001"


async def test_current_sanction_settings_and_queue_operations(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1001, "Tester")
    _seed_assistant(fake_db, 1002, "Helper")

    async with await _client(build_api_app) as client:
        get_policy = await client.get("/api/sanction-settings")
        put_policy = await client.put(
            "/api/sanction-settings",
            json={"daily_norm_spec": 3.5, "daily_norm_mchat": 2},
        )
        get_rules = await client.get("/api/sanction-settings/check-rules")
        put_rules = await client.put(
            "/api/sanction-settings/check-rules",
            json={
                "rules": [
                    {
                        "range_start": 1,
                        "range_end": 2,
                        "penalty_kind": "point",
                        "penalty_amount": 1,
                    }
                ]
            },
        )
        create_operation = await client.post(
            "/api/sanction-operations",
            json={
                "penalty_kind": "point",
                "penalty_amount": 2,
                "recipient_mode": "selected_only",
                "assistant_ids": [1001],
                "workoff_items": [],
            },
        )
        operation_id = create_operation.json()["data"]["id"]
        listed = await client.get("/api/sanction-operations")
        fetched = await client.get(f"/api/sanction-operations/{operation_id}")
        updated = await client.patch(
            f"/api/sanction-operations/{operation_id}",
            json={"penalty_amount": 4, "assistant_ids": [1001]},
        )
        added_member = await client.post(
            f"/api/sanction-operations/{operation_id}/members",
            json={"assistant_id": 1002},
        )
        removed_member = await client.delete(
            f"/api/sanction-operations/{operation_id}/members/1002"
        )
        cancelled = await client.post(f"/api/sanction-operations/{operation_id}/cancel")

    assert get_policy.status_code == 200
    assert "month_start" not in get_policy.json()["data"]
    assert put_policy.status_code == 200
    assert put_policy.json()["data"]["daily_norm_spec"] == 3.5
    assert get_rules.status_code == 200
    assert len(get_rules.json()["data"]) >= 1
    assert put_rules.status_code == 200
    assert put_rules.json()["data"][0]["penalty_kind"] == "point"
    assert create_operation.status_code == 200
    assert create_operation.json()["data"]["queued_at"] is not None
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1
    assert fetched.status_code == 200
    assert fetched.json()["data"]["penalty_amount"] == 2
    assert updated.status_code == 200
    assert updated.json()["data"]["penalty_amount"] == 4
    assert added_member.status_code == 200
    assert len(added_member.json()["data"]["members"]) == 2
    assert removed_member.status_code == 200
    assert len(removed_member.json()["data"]["members"]) == 1
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"


async def test_check_amount_is_fixed_for_manual_queue_update_and_replace(
    build_api_app,
    fake_db,
) -> None:
    _seed_assistant(fake_db, 1001, "Tester")

    async with await _client(build_api_app) as client:
        manual_check = await client.post(
            "/api/assistant-sanctions",
            json={
                "assistant_id": 1001,
                "kind": "check",
                "amount": 7,
                "workoff_items": [],
            },
        )
        point_sanction = await client.post(
            "/api/assistant-sanctions",
            json={
                "assistant_id": 1001,
                "kind": "point",
                "amount": 3,
                "workoff_items": [],
            },
        )
        replace_to_check = await client.post(
            f"/api/assistant-sanctions/{point_sanction.json()['data']['sanction_id']}/replace",
            json={
                "new_kind": "check",
                "new_amount": 9,
                "basis_date": "2026-03-16",
                "workoff_items": [],
            },
        )
        queued_check = await client.post(
            "/api/sanction-operations",
            json={
                "penalty_kind": "check",
                "penalty_amount": 8,
                "recipient_mode": "selected_only",
                "assistant_ids": [1001],
                "workoff_items": [],
            },
        )
        operation_id = queued_check.json()["data"]["id"]
        updated_check = await client.patch(
            f"/api/sanction-operations/{operation_id}",
            json={"penalty_amount": 6},
        )

    assert manual_check.status_code == 200
    assert manual_check.json()["data"]["amount_total"] == 1
    assert fake_db.assistant_sanctions[int(manual_check.json()["data"]["sanction_id"])]["amount_total"] == 1
    assert point_sanction.status_code == 200
    assert replace_to_check.status_code == 200
    assert replace_to_check.json()["data"]["kind"] == "check"
    assert replace_to_check.json()["data"]["amount_total"] == 1
    assert replace_to_check.json()["data"]["active_amount"] == 1
    assert queued_check.status_code == 200
    assert queued_check.json()["data"]["penalty_amount"] == 1
    assert updated_check.status_code == 200
    assert updated_check.json()["data"]["penalty_amount"] == 1
    assert fake_db.queued_sanction_batches[int(operation_id)]["sanction_amount"] == 1


async def test_warning_sanctions_require_auto_relief_date_in_create_and_replace(
    build_api_app,
    fake_db,
) -> None:
    _seed_assistant(fake_db, 1001, "Tester")

    async with await _client(build_api_app) as client:
        manual_missing_date = await client.post(
            "/api/assistant-sanctions",
            json={
                "assistant_id": 1001,
                "kind": "oral",
                "amount": 4,
                "workoff_items": [],
            },
        )
        manual_warning = await client.post(
            "/api/assistant-sanctions",
            json={
                "assistant_id": 1001,
                "kind": "oral",
                "amount": 4,
                "auto_relief_date": "2026-03-20",
                "workoff_items": [],
            },
        )
        point_sanction = await client.post(
            "/api/assistant-sanctions",
            json={
                "assistant_id": 1001,
                "kind": "point",
                "amount": 2,
                "workoff_items": [],
            },
        )
        replace_missing_date = await client.post(
            f"/api/assistant-sanctions/{point_sanction.json()['data']['sanction_id']}/replace",
            json={
                "new_kind": "strict",
                "new_amount": 10,
                "basis_date": "2026-03-16",
                "workoff_items": [],
            },
        )
        queued_missing_date = await client.post(
            "/api/sanction-operations",
            json={
                "penalty_kind": "strict",
                "penalty_amount": 11,
                "recipient_mode": "selected_only",
                "assistant_ids": [1001],
                "workoff_items": [],
            },
        )
        queued_warning = await client.post(
            "/api/sanction-operations",
            json={
                "penalty_kind": "strict",
                "penalty_amount": 11,
                "auto_relief_date": "2026-03-21",
                "recipient_mode": "selected_only",
                "assistant_ids": [1001],
                "workoff_items": [],
            },
        )

    assert manual_missing_date.status_code == 422
    assert "дата автоматического снятия" in manual_missing_date.text
    assert manual_warning.status_code == 200
    assert manual_warning.json()["data"]["amount_total"] == 1
    assert manual_warning.json()["data"]["auto_relief_date"] == "2026-03-20"
    assert point_sanction.status_code == 200
    assert replace_missing_date.status_code == 422
    assert "дата автоматического снятия" in replace_missing_date.text
    assert queued_missing_date.status_code == 422
    assert "дата автоматического снятия" in queued_missing_date.text
    assert queued_warning.status_code == 200
    assert queued_warning.json()["data"]["penalty_amount"] == 1
    assert queued_warning.json()["data"]["auto_relief_date"] == "2026-03-21"


async def test_check_rules_cannot_be_empty(build_api_app, fake_db) -> None:
    async with await _client(build_api_app) as client:
        response = await client.put(
            "/api/sanction-settings/check-rules",
            json={"rules": []},
        )

    assert response.status_code == 422
    assert "хотя бы одно правило" in response.text


async def test_processed_queue_sanctions_expose_display_timestamp(
    build_api_app,
    fake_db,
) -> None:
    _seed_assistant(fake_db, 1001, "Tester")

    async with await _client(build_api_app) as client:
        created = await client.post(
            "/api/sanction-operations",
            json={
                "penalty_kind": "point",
                "penalty_amount": 2,
                "recipient_mode": "selected_only",
                "assistant_ids": [1001],
                "workoff_items": [],
            },
        )
        operation_id = int(created.json()["data"]["id"])
        queued_at = created.json()["data"]["queued_at"]
        await fake_db.process_sanction_operation_now(operation_id, requested_by_id=1)
        active = await client.get("/api/assistants/1001/sanctions/active")

    assert created.status_code == 200
    assert active.status_code == 200
    assert active.json()["data"][0]["source_type"] == "queued_batch"
    assert active.json()["data"][0]["display_issued_at"] == queued_at


async def test_issue_now_processing_copies_auto_relief_date(fake_db) -> None:
    _seed_assistant(fake_db, 1001, "Tester")
    batch = await fake_db.create_queued_sanction_batch(
        basis_date=date(2026, 3, 17),
        created_by_id=1,
        sanction_kind="strict",
        sanction_amount=99,
        auto_relief_date=date(2026, 3, 20),
        audience_mode="selected_only",
        assistant_ids=[1001],
        workoff_items=[],
    )

    result = await fake_db.process_sanction_operation_now(int(batch["id"]), requested_by_id=5)
    active = await fake_db.get_assistant_active_sanctions(1001)

    assert result["processed"] is True
    assert result["status"] == "completed"
    assert len(result["issued"]) == 1
    assert len(active) == 1
    assert active[0]["kind"] == "strict"
    assert active[0]["amount_total"] == 1
    assert active[0]["auto_relief_date"] == "2026-03-20"
    assert active[0]["display_issued_at"] == batch["queued_at"]


async def test_nightly_processing_auto_expires_warning_once(fake_db) -> None:
    _seed_assistant(fake_db, 1001, "Tester")
    sanction = await fake_db.create_manual_sanction(
        assistant_id=1001,
        kind="oral",
        amount=8,
        auto_relief_date=date(2026, 3, 18),
        basis_date=date(2026, 3, 17),
        workoff_items=[],
    )

    first_run = await fake_db.process_queued_sanction_batches_for_date(date(2026, 3, 17))
    second_run = await fake_db.process_queued_sanction_batches_for_date(date(2026, 3, 17))
    sanction_row = fake_db.assistant_sanctions[int(sanction["sanction_id"])]
    auto_reliefs = [
        relief
        for relief in fake_db.sanction_reliefs
        if int(relief["sanction_id"]) == int(sanction["sanction_id"])
        and relief["relief_type"] == "auto_expire"
    ]
    active = await fake_db.get_assistant_active_sanctions(1001)

    assert first_run["warning_auto_expiry"]["relieved"] == [
        {"assistant_id": 1001, "sanction_id": int(sanction["sanction_id"])}
    ]
    assert second_run["warning_auto_expiry"]["relieved"] == []
    assert sanction_row["active_amount"] == 0
    assert len(auto_reliefs) == 1
    assert active == []


async def test_issue_now_queued_operation_publishes_worker_command(
    build_api_app,
    fake_db,
    fake_broker,
) -> None:
    _seed_assistant(fake_db, 1001, "Tester")

    async with await _client(build_api_app) as client:
        created = await client.post(
            "/api/sanction-operations",
            json={
                "penalty_kind": "point",
                "penalty_amount": 2,
                "recipient_mode": "selected_only",
                "assistant_ids": [1001],
                "workoff_items": [],
            },
        )
        operation_id = created.json()["data"]["id"]
        issued = await client.post(f"/api/sanction-operations/{operation_id}/issue-now")

    assert created.status_code == 200
    assert issued.status_code == 202
    assert issued.json()["data"]["id"] == operation_id
    assert any(
        event == "sanction.operation.issue_now"
        and int(payload.get("operation_id", 0)) == int(operation_id)
        for event, payload in fake_broker.calls
    )


async def test_issue_now_rejects_non_queued_operation(build_api_app, fake_db) -> None:
    _seed_assistant(fake_db, 1001, "Tester")

    async with await _client(build_api_app) as client:
        created = await client.post(
            "/api/sanction-operations",
            json={
                "penalty_kind": "point",
                "penalty_amount": 1,
                "recipient_mode": "selected_only",
                "assistant_ids": [1001],
                "workoff_items": [],
            },
        )
        operation_id = created.json()["data"]["id"]
        cancelled = await client.post(f"/api/sanction-operations/{operation_id}/cancel")
        issued = await client.post(f"/api/sanction-operations/{operation_id}/issue-now")

    assert created.status_code == 200
    assert cancelled.status_code == 200
    assert issued.status_code == 409


async def test_issue_now_without_broker_has_predictable_result(
    build_api_app,
    fake_db,
) -> None:
    _seed_assistant(fake_db, 1001, "Tester")
    supports_outbox = all(
        hasattr(
            fake_db,
            method_name,
        )
        for method_name in (
            "enqueue_outbox_message",
            "requeue_stuck_outbox_messages",
            "list_pending_outbox_messages",
            "claim_outbox_message",
            "mark_outbox_message_sent",
            "mark_outbox_message_failed",
        )
    )

    async with await _client(build_api_app, include_broker=False) as client:
        created = await client.post(
            "/api/sanction-operations",
            json={
                "penalty_kind": "point",
                "penalty_amount": 3,
                "recipient_mode": "selected_only",
                "assistant_ids": [1001],
                "workoff_items": [],
            },
        )
        operation_id = created.json()["data"]["id"]
        issued = await client.post(f"/api/sanction-operations/{operation_id}/issue-now")

    assert created.status_code == 200
    assert issued.status_code == (202 if supports_outbox else 503)


async def test_workoff_preview_extends_effective_period_for_leave_day(
    build_api_app,
    fake_db,
) -> None:
    _seed_assistant(fake_db, 1001, "Tester")
    fake_db.current_sanction_policy["daily_norm_spec"] = 4
    fake_db.assistant_day_status_overrides[(1001, "2026-03-02")] = {
        "manual_status": "O",
        "updated_at": datetime.now(MSK),
        "updated_by_id": 1,
    }

    async with await _client(build_api_app) as client:
        response = await client.post(
            "/api/sanctions/workoff-preview",
            json={
                "assistant_ids": [1001],
                "workoff_items": [
                    {
                        "metric": "spec",
                        "multiplier": 1,
                        "period_start": "2026-03-01",
                        "period_end": "2026-03-03",
                    }
                ],
            },
        )

    assert response.status_code == 200
    preview = response.json()["data"]["assistants"][0]["items"][0]
    assert preview["required_work_days"] == 3
    assert preview["uo_days_count"] == 1
    assert preview["effective_period_end"] == "2026-03-04"
    assert any(day["day_status"] == "leave_skipped" for day in preview["days"])


async def test_nightly_processing_skips_leave_day_members(fake_db) -> None:
    _seed_assistant(fake_db, 1001, "Tester")
    fake_db.assistant_day_status_overrides[(1001, "2026-03-18")] = {
        "manual_status": "U",
        "updated_at": datetime.now(MSK),
        "updated_by_id": 1,
    }
    batch = await fake_db.create_queued_sanction_batch(
        basis_date=date(2026, 3, 18),
        created_by_id=1,
        sanction_kind="point",
        sanction_amount=3,
        auto_relief_date=None,
        audience_mode="selected_only",
        assistant_ids=[1001],
        workoff_items=[],
    )

    result = await fake_db.process_queued_sanction_batches_for_date(date(2026, 3, 18), force=True)
    stored_batch = await fake_db.get_queued_sanction_batch(int(batch["id"]))
    active = await fake_db.get_assistant_active_sanctions(1001)

    assert result["processed_batches"][0]["skipped_leave"] == [1001]
    assert stored_batch["skipped_leave_members"] == 1
    assert stored_batch["issued_members"] == 0
    assert active == []


async def test_manual_issue_now_ignores_leave_day(fake_db) -> None:
    _seed_assistant(fake_db, 1001, "Tester")
    fake_db.assistant_day_status_overrides[(1001, "2026-03-18")] = {
        "manual_status": "O",
        "updated_at": datetime.now(MSK),
        "updated_by_id": 1,
    }
    batch = await fake_db.create_queued_sanction_batch(
        basis_date=date(2026, 3, 18),
        created_by_id=1,
        sanction_kind="point",
        sanction_amount=2,
        auto_relief_date=None,
        audience_mode="selected_only",
        assistant_ids=[1001],
        workoff_items=[],
    )

    result = await fake_db.process_sanction_operation_now(int(batch["id"]), requested_by_id=5)
    active = await fake_db.get_assistant_active_sanctions(1001)

    assert result["processed"] is True
    assert result["issued"] == [{"assistant_id": 1001, "sanction_id": active[0]["sanction_id"]}]
    assert result["skipped_leave"] == []
    assert len(active) == 1
