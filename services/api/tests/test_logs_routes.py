from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from routes.logs import router as logs_router

pytestmark = pytest.mark.anyio


async def _client(build_api_app, current_user=None):
    app = build_api_app(logs_router, current_user=current_user)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_admin_logs_requires_permission(build_api_app) -> None:
    current_user = {
        "id": 1,
        "username": "viewer",
        "nickname": "Viewer",
        "role": "employee",
        "discord_id": 1001,
        "require_password_change": False,
        "permissions": {"can_view_admin_logs": False},
    }

    async with await _client(build_api_app, current_user=current_user) as client:
        response = await client.get("/api/logs/admin")

    assert response.status_code == 403
    assert "Недостаточно прав" in response.json()["detail"]


async def test_get_admin_logs_with_filters_and_sort(build_api_app, fake_db) -> None:
    fake_db.admin_logs_entries = [
        {
            "id": 1,
            "actor_name": "Zed",
            "admin_name": "Zed",
            "action": "user.create",
            "target_name": "user1",
            "target_type": "user",
            "created_at": "2026-02-10T10:00:00",
        },
        {
            "id": 2,
            "actor_name": "Alice",
            "admin_name": "Alice",
            "action": "streamer.update",
            "target_name": "streamer1",
            "target_type": "streamer",
            "created_at": "2026-02-11T10:00:00",
        },
        {
            "id": 3,
            "actor_name": "Bob",
            "admin_name": "Bob",
            "action": "user.create",
            "target_name": "user2",
            "target_type": "user",
            "created_at": "2026-02-12T10:00:00",
        },
    ]

    current_user = {
        "id": 10,
        "username": "manager",
        "nickname": "Manager",
        "role": "manager",
        "discord_id": 500,
        "require_password_change": False,
        "permissions": {"can_view_admin_logs": True},
    }

    async with await _client(build_api_app, current_user=current_user) as client:
        response = await client.get(
            "/api/logs/admin",
            params={
                "limit": 2,
                "offset": 0,
                "action": ["user.create"],
                "sort_by": "actor_name",
                "sort_order": "asc",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["actor_name"] == "Bob"
