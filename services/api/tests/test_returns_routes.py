from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from routes.returns import router as returns_router

pytestmark = pytest.mark.anyio


async def _client(build_api_app, current_user: dict | None = None):
    app = build_api_app(returns_router, current_user=current_user)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _employee_user(discord_id: int, nickname: str) -> dict:
    return {
        "id": discord_id,
        "username": nickname.lower(),
        "nickname": nickname,
        "role": "employee",
        "principal_type": "user",
        "discord_id": discord_id,
        "require_password_change": False,
        "permissions": {
            "returns.view": True,
            "returns.create": True,
            "returns.execute": True,
            "returns.history.view": True,
            "returns.manage.self": True,
        },
    }


def _manager_user(discord_id: int, nickname: str) -> dict:
    base = _employee_user(discord_id, nickname)
    base["role"] = "manager"
    base["permissions"]["returns.manage.any"] = True
    base["permissions"]["logs.admin.view"] = True
    return base


async def _seed_return(
    fake_db,
    *,
    removed_by_id: int = 1001,
    removed_by_name: str = "Creator",
    punishment_type: str = "mute",
    static: int = 27253,
    server: int = 14,
    duration: int = 60,
    remove_reason: str = "На видео",
    status: str = "pending",
):
    record = await fake_db.create_punishment_return(
        punishment_type=punishment_type,
        static=static,
        server=server,
        duration=duration,
        remove_reason=remove_reason,
        discord_message_url="https://discord.com/channels/test/message",
        removed_by_id=removed_by_id,
        removed_by_name=removed_by_name,
    )
    assert record is not None
    fake_db.punishment_returns[record["id"]]["status"] = status
    return record["id"]


async def test_create_return_generates_commands(build_api_app, fake_db) -> None:
    user = _employee_user(2001, "akudama")

    async with await _client(build_api_app, current_user=user) as client:
        response = await client.post(
            "/api/returns",
            json={
                "punishment_type": "mute",
                "static": 27253,
                "server": 14,
                "duration": 60,
                "remove_reason": "На видео",
                "discord_message_url": "https://discord.com/channels/test/message",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["static"] == 27253
    assert data["server"] == 14
    assert data["remove_command"] == "/unmute 27253 На видео by akudama"
    assert data["return_command"] == "/mute 27253 120 Возврат наказания by akudama"
    assert data["can_edit"] is True


async def test_create_return_allows_missing_discord_link(build_api_app, fake_db) -> None:
    user = _employee_user(2001, "akudama")

    async with await _client(build_api_app, current_user=user) as client:
        response = await client.post(
            "/api/returns",
            json={
                "punishment_type": "mute",
                "static": 27253,
                "server": 14,
                "duration": 60,
                "remove_reason": "На видео",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["discord_message_url"] is None
    assert data["remove_command"] == "/unmute 27253 На видео by akudama"


async def test_queue_status_labels_and_claim_ready_record(build_api_app, fake_db) -> None:
    user = _employee_user(2001, "hamesse")
    return_id = await _seed_return(fake_db, removed_by_id=2001, removed_by_name="hamesse")
    fake_db.punishment_returns[return_id]["removed_at"] -= timedelta(hours=13)

    async with await _client(build_api_app, current_user=user) as client:
        queue_response = await client.get("/api/returns/queue")
        claim_response = await client.post(f"/api/returns/{return_id}/claim")

    assert queue_response.status_code == 200
    queue_item = queue_response.json()["data"][0]
    assert queue_item["status_label"] == "Готово"
    assert queue_item["can_claim"] is True

    assert claim_response.status_code == 200
    claimed = claim_response.json()["data"]
    assert claimed["status"] == "claimed"
    assert claimed["status_label"] == "В работе: hamesse"
    assert claimed["can_complete"] is True


async def test_claimer_can_release_return_back_to_queue(build_api_app, fake_db) -> None:
    user = _employee_user(2001, "hamesse")
    return_id = await _seed_return(fake_db, removed_by_id=2001, removed_by_name="hamesse")
    fake_db.punishment_returns[return_id]["removed_at"] -= timedelta(hours=13)

    async with await _client(build_api_app, current_user=user) as client:
        claim_response = await client.post(f"/api/returns/{return_id}/claim")
        release_response = await client.post(f"/api/returns/{return_id}/release")

    assert claim_response.status_code == 200
    assert release_response.status_code == 200
    released = release_response.json()["data"]
    assert released["status"] == "pending"
    assert released["claimed_by_id"] is None
    assert released["claimed_by_name"] is None
    assert released["status_label"] == "Готово"
    assert released["can_claim"] is True


async def test_claim_conflict_when_not_ready(build_api_app, fake_db) -> None:
    user = _employee_user(2001, "hamesse")
    return_id = await _seed_return(fake_db)

    async with await _client(build_api_app, current_user=user) as client:
        response = await client.post(f"/api/returns/{return_id}/claim")

    assert response.status_code == 409
    assert response.json()["code"] == "RETURN_NOT_READY"


async def test_complete_only_for_claimer_or_manager(build_api_app, fake_db) -> None:
    creator = _employee_user(2001, "akudama")
    other_employee = _employee_user(2002, "rodnoy")
    manager = _manager_user(3001, "gamzol")
    return_id = await _seed_return(
        fake_db,
        removed_by_id=creator["discord_id"],
        removed_by_name=creator["nickname"],
    )
    fake_db.punishment_returns[return_id]["removed_at"] -= timedelta(hours=13)

    async with await _client(build_api_app, current_user=creator) as creator_client:
        claim_response = await creator_client.post(f"/api/returns/{return_id}/claim")
    assert claim_response.status_code == 200

    async with await _client(build_api_app, current_user=other_employee) as employee_client:
        forbidden_response = await employee_client.post(f"/api/returns/{return_id}/complete")
    assert forbidden_response.status_code == 403

    async with await _client(build_api_app, current_user=manager) as manager_client:
        complete_response = await manager_client.post(f"/api/returns/{return_id}/complete")
    assert complete_response.status_code == 200
    completed = complete_response.json()["data"]
    assert completed["status"] == "completed"
    assert completed["completed_by_name"] == "gamzol"


async def test_manage_self_is_blocked_after_claim(build_api_app, fake_db) -> None:
    author = _employee_user(2001, "akudama")
    return_id = await _seed_return(
        fake_db,
        removed_by_id=author["discord_id"],
        removed_by_name=author["nickname"],
    )

    async with await _client(build_api_app, current_user=author) as client:
        patch_ok = await client.patch(
            f"/api/returns/{return_id}",
            json={"duration": 45},
        )
    assert patch_ok.status_code == 200
    assert patch_ok.json()["data"]["duration"] == 45

    fake_db.punishment_returns[return_id]["removed_at"] -= timedelta(hours=13)
    fake_db.punishment_returns[return_id]["status"] = "claimed"
    fake_db.punishment_returns[return_id]["claimed_by_id"] = author["discord_id"]
    fake_db.punishment_returns[return_id]["claimed_by_name"] = author["nickname"]
    fake_db.punishment_returns[return_id]["claimed_at"] = fake_db.punishment_returns[return_id]["removed_at"] + timedelta(hours=13)

    async with await _client(build_api_app, current_user=author) as client:
        patch_forbidden = await client.patch(
            f"/api/returns/{return_id}",
            json={"duration": 30},
        )
        delete_forbidden = await client.delete(f"/api/returns/{return_id}")

    assert patch_forbidden.status_code == 403
    assert delete_forbidden.status_code == 403


async def test_manage_any_delete_logs_admin_action_and_history_filters(build_api_app, fake_db) -> None:
    manager = _manager_user(3001, "gamzol")
    completed_id = await _seed_return(
        fake_db,
        removed_by_id=2001,
        removed_by_name="akudama",
        punishment_type="jail",
        static=138254,
        server=14,
        duration=13,
        remove_reason="На стрим",
        status="completed",
    )
    fake_db.punishment_returns[completed_id]["completed_by_id"] = 2002
    fake_db.punishment_returns[completed_id]["completed_by_name"] = "hamesse"
    fake_db.punishment_returns[completed_id]["completed_at"] = fake_db.punishment_returns[completed_id]["removed_at"] + timedelta(hours=13)

    deletable_id = await _seed_return(fake_db, static=50001, server=7)

    async with await _client(build_api_app, current_user=manager) as client:
        history_response = await client.get(
            "/api/returns/history",
            params={
                "static": 138254,
                "server": 14,
                "removed_by": "aku",
                "completed_by": "ham",
                "punishment_type": "jail",
            },
        )
        delete_response = await client.delete(f"/api/returns/{deletable_id}")

    assert history_response.status_code == 200
    payload = history_response.json()["data"]
    assert payload["total"] == 1
    assert payload["items"][0]["static"] == 138254
    assert payload["items"][0]["completed_by_name"] == "hamesse"

    assert delete_response.status_code == 200
    assert fake_db.logged_actions[-1]["action"] == "return.delete"
