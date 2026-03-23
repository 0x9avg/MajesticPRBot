from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

removals_router = pytest.importorskip("routes.removals").router

pytestmark = pytest.mark.anyio

MSK = timezone(timedelta(hours=3))


async def _client(build_api_app, current_user: dict | None = None):
    app = build_api_app(removals_router, current_user=current_user)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _removals_user(
    discord_id: int,
    nickname: str,
    *,
    manage_any: bool = False,
    history_only: bool = False,
) -> dict:
    permissions = {"removals.history.view": True}
    if not history_only:
        permissions.update(
            {
                "removals.queue.view": True,
                "removals.create": True,
                "removals.issue": True,
                "removals.manage.self": True,
            }
        )
    if manage_any:
        permissions["removals.manage.any"] = True
        permissions["logs.admin.view"] = True
    return {
        "id": discord_id,
        "username": nickname.lower(),
        "nickname": nickname,
        "role": "manager" if manage_any else "employee",
        "principal_type": "user",
        "discord_id": discord_id,
        "require_password_change": False,
        "permissions": permissions,
    }


async def _seed_removal(
    fake_db,
    *,
    assistant_id: int,
    assistant_name: str,
    status: str = "draft",
    removal_type: str = "unmute",
    static: int = 27253,
    server: int = 14,
    reason: str = "На видео",
    message_link: str = "https://discord.com/channels/test/message",
    created_at: datetime | None = None,
    issued_at: datetime | None = None,
    reviewed_at: datetime | None = None,
) -> int:
    record = await fake_db.create_punishment_removal(
        assistant_id=assistant_id,
        assistant_name=assistant_name,
        removal_type=removal_type,
        violator_static=static,
        server=server,
        reason=reason,
        message_link=message_link,
        status=status,
        created_at=created_at,
        issued_at=issued_at,
        reviewed_at=reviewed_at,
    )
    assert record is not None
    return int(record["id"])


async def test_removals_lifecycle_allows_author_submit_issue_and_admin_edit(
    build_api_app,
    fake_db,
) -> None:
    author = _removals_user(2001, "akudama")
    manager = _removals_user(3001, "gamzol", manage_any=True)
    other = _removals_user(2002, "rodnoy")

    async with await _client(build_api_app, current_user=author) as client:
        create_response = await client.post(
            "/api/removals",
            json={
                "target_status": "draft",
                "removal_type": "unmute",
                "static": 27253,
                "server": 14,
                "reason": "На видео",
                "message_link": "https://discord.com/channels/test/message",
            },
        )

    assert create_response.status_code == 200
    removal = create_response.json()["data"]
    removal_id = int(removal["id"])
    assert removal["status"] == "draft"
    assert removal["command"].startswith("/unmute")

    async with await _client(build_api_app, current_user=author) as author_client:
        queue_response = await author_client.get("/api/removals/queue")
        detail_response = await author_client.get(f"/api/removals/{removal_id}")

    assert queue_response.status_code == 200
    assert len(queue_response.json()["data"]) == 1
    assert queue_response.json()["data"][0]["status"] == "draft"
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["command"].startswith("/unmute")

    async with await _client(build_api_app, current_user=other) as other_client:
        other_queue = await other_client.get("/api/removals/queue")

    assert other_queue.status_code == 200
    assert not any(row["id"] == removal_id for row in other_queue.json()["data"])

    async with await _client(build_api_app, current_user=author) as author_client:
        submit_response = await author_client.patch(
            f"/api/removals/{removal_id}",
            json={"target_status": "pending"},
        )
        issue_response = await author_client.post(f"/api/removals/{removal_id}/issue")

    assert submit_response.status_code == 200
    assert submit_response.json()["data"]["status"] == "pending"
    assert issue_response.status_code == 200
    issued = issue_response.json()["data"]
    assert issued["status"] == "issued"
    assert issued["issued_by_name"] == "akudama"
    assert issued["issued_at"] is not None

    async with await _client(build_api_app, current_user=author) as author_client:
        history_response = await author_client.get("/api/removals/history")
        author_patch = await author_client.patch(
            f"/api/removals/{removal_id}",
            json={"reason": "На стрим"},
        )
        author_delete = await author_client.delete(f"/api/removals/{removal_id}")

    assert history_response.status_code == 200
    assert len(history_response.json()["data"]["items"]) == 1
    assert author_patch.status_code in {403, 404}
    assert author_delete.status_code in {403, 404}

    async with await _client(build_api_app, current_user=manager) as manager_client:
        manager_patch = await manager_client.patch(
            f"/api/removals/{removal_id}",
            json={"reason": "На стрим"},
        )
        manager_delete = await manager_client.delete(f"/api/removals/{removal_id}")

    assert manager_patch.status_code == 200
    assert manager_patch.json()["data"]["reason"] == "На стрим"
    assert manager_delete.status_code == 200


async def test_removals_history_only_user_cannot_access_queue(build_api_app, fake_db) -> None:
    history_user = _removals_user(4001, "history", history_only=True)
    author = _removals_user(2001, "akudama")
    removal_id = await _seed_removal(
        fake_db,
        assistant_id=author["discord_id"],
        assistant_name=author["nickname"],
        status="issued",
        issued_at=datetime(2026, 3, 19, 12, 0, tzinfo=MSK),
        reviewed_at=datetime(2026, 3, 19, 11, 0, tzinfo=MSK),
    )

    async with await _client(build_api_app, current_user=history_user) as client:
        queue_response = await client.get("/api/removals/queue")
        history_response = await client.get("/api/removals/history")

    assert queue_response.status_code == 403
    assert history_response.status_code == 200
    assert len(history_response.json()["data"]["items"]) == 1


async def test_removals_require_issue_ready_status_and_admin_only_issue_controls(
    build_api_app,
    fake_db,
) -> None:
    author = _removals_user(2001, "akudama")
    manager = _removals_user(3001, "gamzol", manage_any=True)
    removal_id = await _seed_removal(
        fake_db,
        assistant_id=author["discord_id"],
        assistant_name=author["nickname"],
        status="pending",
    )

    async with await _client(build_api_app, current_user=author) as author_client:
        issue_response = await author_client.post(f"/api/removals/{removal_id}/issue")

    assert issue_response.status_code == 200
    assert issue_response.json()["data"]["status"] == "issued"

    async with await _client(build_api_app, current_user=author) as author_client:
        author_patch = await author_client.patch(
            f"/api/removals/{removal_id}",
            json={"reason": "На стрим"},
        )
        author_delete = await author_client.delete(f"/api/removals/{removal_id}")

    assert author_patch.status_code in {403, 404}
    assert author_delete.status_code in {403, 404}

    async with await _client(build_api_app, current_user=manager) as manager_client:
        manager_patch = await manager_client.patch(
            f"/api/removals/{removal_id}",
            json={"reason": "На стрим"},
        )
        manager_delete = await manager_client.delete(f"/api/removals/{removal_id}")

    assert manager_patch.status_code == 200
    assert manager_delete.status_code == 200


async def test_removals_reject_invalid_reason_enum(build_api_app) -> None:
    author = _removals_user(2001, "akudama")

    async with await _client(build_api_app, current_user=author) as client:
        create_response = await client.post(
            "/api/removals",
            json={
                "target_status": "draft",
                "removal_type": "unmute",
                "static": 27253,
                "server": 14,
                "reason": "Свободный текст",
                "message_link": "https://discord.com/channels/test/message",
            },
        )

    assert create_response.status_code == 422


async def test_removals_history_server_filter_accepts_inactive_server(
    build_api_app,
    fake_db,
) -> None:
    author = _removals_user(2001, "akudama")
    await _seed_removal(
        fake_db,
        assistant_id=author["discord_id"],
        assistant_name=author["nickname"],
        status="issued",
        server=14,
        issued_at=datetime(2026, 3, 19, 12, 0, tzinfo=MSK),
        reviewed_at=datetime(2026, 3, 19, 11, 0, tzinfo=MSK),
    )
    fake_db.game_servers_by_id[14]["is_active"] = False

    async with await _client(build_api_app, current_user=author) as client:
        response = await client.get("/api/removals/history?server=14")

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
