from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

complaints_router = pytest.importorskip("routes.complaints").router

pytestmark = pytest.mark.anyio

MSK = timezone(timedelta(hours=3))


async def _client(build_api_app, current_user: dict | None = None):
    app = build_api_app(complaints_router, current_user=current_user)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _complaints_user(
    discord_id: int,
    nickname: str,
    *,
    manage_any: bool = False,
    history_only: bool = False,
) -> dict:
    permissions = {"complaints.history.view": True}
    if not history_only:
        permissions.update(
            {
                "complaints.queue.view": True,
                "complaints.create": True,
                "complaints.issue": True,
                "complaints.manage.self": True,
            }
        )
    if manage_any:
        permissions["complaints.manage.any"] = True
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


async def _seed_complaint(
    fake_db,
    *,
    assistant_id: int,
    assistant_name: str,
    status: str = "draft",
    server: int = 14,
    complaint_link: str = "https://discord.com/channels/test/complaint",
    media: str = "maison",
    incident_at: datetime | None = None,
    issued_at: datetime | None = None,
    reviewed_at: datetime | None = None,
    punishments: list[dict[str, object]] | None = None,
) -> int:
    record = await fake_db.create_complaint(
        assistant_id=assistant_id,
        created_by_id=assistant_id,
        created_by_name=assistant_name,
        server=server,
        complaint_link=complaint_link,
        media=media,
        incident_at=incident_at or datetime(2026, 3, 18, 12, 0, tzinfo=MSK),
        status=status,
        issued_at=issued_at,
        reviewed_at=reviewed_at,
        punishments=punishments
        or [
            {
                "punishment_type": "mute",
                "static": 27253,
                "duration": 60,
                "reason": "Spam",
            }
        ],
    )
    assert record is not None
    return int(record["id"])


async def test_complaint_lifecycle_returns_complaint_level_queue_and_history_items(
    build_api_app,
    fake_db,
) -> None:
    author = _complaints_user(2001, "akudama")
    manager = _complaints_user(3001, "gamzol", manage_any=True)
    other = _complaints_user(2002, "rodnoy")

    async with await _client(build_api_app, current_user=author) as client:
        missing_media_create = await client.post(
            "/api/complaints",
            json={
                "target_status": "draft",
                "server": 14,
                "complaint_link": "https://discord.com/channels/test/complaint",
                "incident_at": "2026-03-18T12:00:00+03:00",
                "punishments": [
                    {
                        "punishment_type": "mute",
                        "static": 27253,
                        "duration": 60,
                        "reason": "Spam",
                    }
                ],
            },
        )
        create_response = await client.post(
            "/api/complaints",
            json={
                "target_status": "draft",
                "server": 14,
                "complaint_link": "https://discord.com/channels/test/complaint",
                "media": "maison",
                "incident_at": "2026-03-18T12:00:00+03:00",
                "punishments": [
                    {
                        "punishment_type": "mute",
                        "static": 27253,
                        "duration": 60,
                        "reason": "Spam",
                    },
                    {
                        "punishment_type": "ajail",
                        "static": 138254,
                        "duration": 24,
                        "reason": "Flood",
                    },
                ],
            },
        )

    assert missing_media_create.status_code == 422
    assert create_response.status_code == 200
    complaint = create_response.json()["data"]
    complaint_id = int(complaint["id"])
    assert complaint["status"] == "draft"
    assert complaint["server"] == 14
    assert complaint["aggregate_command"]
    assert complaint["aggregate_message"]
    assert len(complaint["punishments"]) == 2
    assert complaint["punishments"][0]["command"]
    assert complaint["punishments"][1]["command"]

    async with await _client(build_api_app, current_user=author) as author_client:
        queue_response = await author_client.get("/api/complaints/queue")
        detail_response = await author_client.get(f"/api/complaints/{complaint_id}")
        missing_media_update = await author_client.patch(
            f"/api/complaints/{complaint_id}",
            json={"server": 15},
        )

    assert queue_response.status_code == 200
    queue_items = queue_response.json()["data"]
    assert len(queue_items) == 1
    queue_item = queue_items[0]
    assert queue_item["complaint_id"] == complaint_id
    assert queue_item["id"] == complaint_id
    assert queue_item["punishments_count"] == 2
    assert len(queue_item["punishments"]) == 2
    assert {row["punishment_type"] for row in queue_item["punishments"]} == {"mute", "ajail"}
    assert "/mute 27253 60 Spam (media-жалоба maison | 12:00 18.03) by akudama" in queue_item["aggregate_command"]
    assert "/ajail 138254 24 Flood (media-жалоба maison | 12:00 18.03) by akudama" in queue_item["aggregate_command"]
    assert "Игрок #27253 получил Mute на 60 минут за Spam" in queue_item["aggregate_message"]
    assert "Игрок #138254 получил Ajail на 24 минут за Flood" in queue_item["aggregate_message"]
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["aggregate_command"] == queue_item["aggregate_command"]
    assert detail["aggregate_message"] == queue_item["aggregate_message"]
    assert len(detail["punishments"]) == 2
    assert detail["punishments"][0]["punishment_type"] == "mute"
    assert detail["punishments"][0]["command"] == "/mute 27253 60 Spam (media-жалоба maison | 12:00 18.03) by akudama"
    assert missing_media_update.status_code == 422

    async with await _client(build_api_app, current_user=other) as other_client:
        other_queue = await other_client.get("/api/complaints/queue")

    assert other_queue.status_code == 200
    assert not any(row["complaint_id"] == complaint_id for row in other_queue.json()["data"])

    async with await _client(build_api_app, current_user=author) as author_client:
        submit_response = await author_client.patch(
            f"/api/complaints/{complaint_id}",
            json={"target_status": "pending"},
        )
        issue_response = await author_client.post(f"/api/complaints/{complaint_id}/issue")

    assert submit_response.status_code == 200
    assert submit_response.json()["data"]["status"] == "pending"
    assert issue_response.status_code == 200
    issued = issue_response.json()["data"]
    assert issued["status"] == "issued"
    assert issued["issued_by_name"] == "akudama"
    assert issued["issued_at"] is not None
    assert issued["aggregate_command"]
    assert issued["aggregate_message"]

    async with await _client(build_api_app, current_user=author) as author_client:
        history_response = await author_client.get("/api/complaints/history")
        author_patch = await author_client.patch(
            f"/api/complaints/{complaint_id}",
            json={"media": "https://cdn.example/media-updated.png"},
        )
        author_delete = await author_client.delete(f"/api/complaints/{complaint_id}")

    assert history_response.status_code == 200
    history_items = history_response.json()["data"]["items"]
    assert len(history_items) == 1
    history_item = history_items[0]
    assert history_item["complaint_id"] == complaint_id
    assert history_item["server"] == 14
    assert len(history_item["punishments"]) == 2
    assert history_item["aggregate_command"]
    assert history_item["aggregate_message"]
    assert author_patch.status_code in {403, 404}
    assert author_delete.status_code in {403, 404}

    async with await _client(build_api_app, current_user=manager) as manager_client:
        manager_patch = await manager_client.patch(
            f"/api/complaints/{complaint_id}",
            json={"media": "media-admin"},
        )
        manager_delete = await manager_client.delete(f"/api/complaints/{complaint_id}")

    assert manager_patch.status_code == 200
    assert manager_patch.json()["data"]["media"] == "media-admin"
    assert manager_delete.status_code == 200


async def test_complaints_history_only_user_cannot_access_queue(build_api_app, fake_db) -> None:
    history_user = _complaints_user(4001, "history", history_only=True)
    author = _complaints_user(2001, "akudama")
    complaint_id = await _seed_complaint(
        fake_db,
        assistant_id=author["discord_id"],
        assistant_name=author["nickname"],
        status="issued",
        issued_at=datetime(2026, 3, 19, 12, 0, tzinfo=MSK),
        reviewed_at=datetime(2026, 3, 19, 11, 0, tzinfo=MSK),
        punishments=[
            {
                "punishment_type": "mute",
                "static": 27253,
                "duration": 60,
                "reason": "Spam",
            }
        ],
    )

    async with await _client(build_api_app, current_user=history_user) as client:
        queue_response = await client.get("/api/complaints/queue")
        history_response = await client.get("/api/complaints/history")

    assert queue_response.status_code == 403
    assert history_response.status_code == 200
    history_items = history_response.json()["data"]["items"]
    assert len(history_items) == 1
    assert len(history_items[0]["punishments"]) == 1


async def test_complaints_require_at_least_one_punishment_and_block_last_child_delete(
    build_api_app,
    fake_db,
) -> None:
    author = _complaints_user(2001, "akudama")
    complaint_id = await _seed_complaint(
        fake_db,
        assistant_id=author["discord_id"],
        assistant_name=author["nickname"],
        punishments=[
            {
                "punishment_type": "mute",
                "static": 27253,
                "duration": 60,
                "reason": "Spam",
            }
        ],
    )
    complaint = await fake_db.get_complaint(complaint_id)
    punishment_id = int(complaint["punishments"][0]["id"])

    async with await _client(build_api_app, current_user=author) as client:
        empty_create = await client.post(
            "/api/complaints",
            json={
                "target_status": "draft",
                "server": 14,
                "complaint_link": "https://discord.com/channels/test/complaint",
                "media": "maison",
                "incident_at": "2026-03-18T12:00:00+03:00",
                "punishments": [],
            },
        )
        delete_child = await client.delete(
            f"/api/complaints/{complaint_id}/punishments/{punishment_id}"
        )

    assert empty_create.status_code == 422
    assert delete_child.status_code in {400, 409}
    still_present = await fake_db.get_complaint(complaint_id)
    assert still_present is not None
    assert len(still_present["punishments"]) == 1


async def test_complaints_history_filters_match_nested_punishments_and_count_headers(
    build_api_app,
    fake_db,
) -> None:
    author = _complaints_user(2001, "akudama")

    first_id = await _seed_complaint(
        fake_db,
        assistant_id=author["discord_id"],
        assistant_name=author["nickname"],
        status="issued",
        media="maison",
        issued_at=datetime(2026, 3, 19, 12, 0, tzinfo=MSK),
        reviewed_at=datetime(2026, 3, 19, 11, 0, tzinfo=MSK),
        punishments=[
            {
                "punishment_type": "mute",
                "static": 27253,
                "duration": 60,
                "reason": "Spam",
            },
            {
                "punishment_type": "gunban",
                "static": 427002,
                "duration": 6,
                "reason": "DM",
            },
        ],
    )
    second_id = await _seed_complaint(
        fake_db,
        assistant_id=author["discord_id"],
        assistant_name=author["nickname"],
        status="issued",
        media="snikers",
        issued_at=datetime(2026, 3, 19, 13, 0, tzinfo=MSK),
        reviewed_at=datetime(2026, 3, 19, 12, 30, tzinfo=MSK),
        punishments=[
            {
                "punishment_type": "warn",
                "static": 90001,
                "duration": None,
                "reason": "Offtopic",
            }
        ],
    )

    async with await _client(build_api_app, current_user=author) as client:
        by_static = await client.get("/api/complaints/history?static=427002")
        by_type = await client.get("/api/complaints/history?punishment_type=gunban")

    assert by_static.status_code == 200
    static_payload = by_static.json()["data"]
    assert static_payload["total"] == 1
    assert len(static_payload["items"]) == 1
    assert static_payload["items"][0]["id"] == first_id
    assert static_payload["items"][0]["punishments_count"] == 2

    assert by_type.status_code == 200
    type_payload = by_type.json()["data"]
    assert type_payload["total"] == 1
    assert len(type_payload["items"]) == 1
    assert type_payload["items"][0]["id"] == first_id
    assert type_payload["items"][0]["id"] != second_id


async def test_complaint_update_rejects_null_server_payload(build_api_app, fake_db) -> None:
    author = _complaints_user(2001, "akudama")
    complaint = await fake_db.create_complaint(
        assistant_id=author["discord_id"],
        created_by_id=author["discord_id"],
        created_by_name=author["nickname"],
        server=14,
        complaint_link="https://discord.com/channels/test/complaint",
        media="https://cdn.example/media.png",
        incident_at=datetime(2026, 3, 18, 12, 0, tzinfo=MSK),
        status="draft",
        punishments=[
            {
                "punishment_type": "mute",
                "static": 27253,
                "duration": 60,
                "reason": "Spam",
            }
        ],
    )
    assert complaint is not None

    async with await _client(build_api_app, current_user=author) as client:
        response = await client.patch(
            f"/api/complaints/{int(complaint['id'])}",
            json={"server": None, "media": "https://cdn.example/media.png"},
        )

    assert response.status_code == 422


async def test_complaints_history_server_filter_accepts_inactive_server(
    build_api_app,
    fake_db,
) -> None:
    author = _complaints_user(2001, "akudama")
    await fake_db.create_complaint(
        assistant_id=author["discord_id"],
        created_by_id=author["discord_id"],
        created_by_name=author["nickname"],
        server=14,
        complaint_link="https://discord.com/channels/test/complaint",
        media="https://cdn.example/media.png",
        incident_at=datetime(2026, 3, 18, 12, 0, tzinfo=MSK),
        status="issued",
        reviewed_at=datetime(2026, 3, 18, 13, 0, tzinfo=MSK),
        issued_at=datetime(2026, 3, 18, 14, 0, tzinfo=MSK),
        punishments=[
            {
                "punishment_type": "mute",
                "static": 27253,
                "duration": 60,
                "reason": "Spam",
            }
        ],
    )
    fake_db.game_servers_by_id[14]["is_active"] = False

    async with await _client(build_api_app, current_user=author) as client:
        response = await client.get("/api/complaints/history?server=14")

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
