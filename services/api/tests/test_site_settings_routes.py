from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from routes.site_settings import router as site_settings_router

pytestmark = pytest.mark.anyio


def _developer_user() -> dict:
    return {
        "id": 99,
        "username": "developer",
        "nickname": "Developer",
        "role": "developer",
        "principal_type": "user",
        "discord_id": 9001,
        "require_password_change": False,
        "permissions": {
            "rbac.view": True,
            "rbac.update": True,
            "site.maintenance.view": True,
            "site.maintenance.update": True,
            "maintenance.bypass": True,
            "admin.panel.view": True,
        },
    }


def _manager_user() -> dict:
    return {
        "id": 55,
        "username": "manager",
        "nickname": "Manager",
        "role": "manager",
        "principal_type": "user",
        "discord_id": 5001,
        "require_password_change": False,
        "permissions": {
            "rbac.view": True,
            "rbac.update": True,
            "site.maintenance.view": True,
            "site.maintenance.update": True,
            "admin.panel.view": True,
        },
    }


async def _client(build_api_app, current_user: dict | None = None):
    app = build_api_app(
        site_settings_router,
        current_user=current_user or _developer_user(),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_rbac_snapshot(build_api_app) -> None:
    async with await _client(build_api_app) as client:
        response = await client.get("/api/admin/rbac")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["roles"] == [
        "junior_employee",
        "employee",
        "senior_employee",
        "manager",
        "developer",
    ]
    assert "rbac.view" in payload["permissions"]
    assert payload["permission_implications"]["assistants.sessions.manage"] == [
        "assistants.sessions.view",
        "assistants.view",
        "admin.panel.view",
    ]
    assert payload["permission_implications"]["media.delete"] == ["media.view"]
    assert payload["permission_implications"]["events.runtime.manage"] == ["events.view"]
    assert payload["matrix"]["manager"]["rbac.update"] is False
    assert payload["matrix"]["manager"]["site.maintenance.update"] is False
    assert payload["matrix"]["manager"]["admin.panel.view"] is True


async def test_patch_site_maintenance(build_api_app, fake_db) -> None:
    async with await _client(build_api_app) as client:
        response = await client.patch(
            "/api/admin/site-maintenance",
            json={"enabled": True},
        )

    assert response.status_code == 200
    assert fake_db.site_maintenance_enabled is True
    assert response.json()["data"]["enabled"] is True
    assert any(
        log["action"] == "site.maintenance.update"
        for log in fake_db.logged_actions
    )


async def test_put_rbac_updates_snapshot(build_api_app, fake_db) -> None:
    async with await _client(build_api_app) as client:
        initial = await client.get("/api/admin/rbac")

    matrix = initial.json()["data"]["matrix"]
    matrix["manager"]["assistants.weekly.manage"] = False
    matrix["manager"]["rbac.view"] = True

    async with await _client(build_api_app) as client:
        response = await client.put(
            "/api/admin/rbac",
            json={"matrix": matrix},
        )

    assert response.status_code == 200
    assert fake_db.role_permissions["manager"]["assistants.weekly.manage"] is False
    assert fake_db.role_permissions["manager"]["rbac.view"] is True
    assert response.json()["data"]["matrix"]["manager"]["assistants.weekly.manage"] is False
    assert any(
        log["action"] == "rbac.matrix.update"
        for log in fake_db.logged_actions
    )


async def test_put_rbac_applies_permission_implications(build_api_app) -> None:
    async with await _client(build_api_app) as client:
        initial = await client.get("/api/admin/rbac")

    matrix = initial.json()["data"]["matrix"]
    matrix["manager"]["assistants.sessions.manage"] = True
    matrix["manager"]["media.delete"] = True
    matrix["manager"]["events.runtime.manage"] = True

    async with await _client(build_api_app) as client:
        response = await client.put(
            "/api/admin/rbac",
            json={"matrix": matrix},
        )

    assert response.status_code == 200
    payload = response.json()["data"]["matrix"]["manager"]
    assert payload["assistants.sessions.manage"] is True
    assert payload["assistants.sessions.view"] is True
    assert payload["assistants.view"] is True
    assert payload["media.delete"] is True
    assert payload["media.view"] is True
    assert payload["events.runtime.manage"] is True
    assert payload["events.view"] is True


async def test_get_rbac_snapshot_hides_same_rank_and_higher_roles_for_manager(
    build_api_app,
) -> None:
    async with await _client(build_api_app, current_user=_manager_user()) as client:
        response = await client.get("/api/admin/rbac")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["roles"] == [
        "junior_employee",
        "employee",
        "senior_employee",
    ]
    assert "manager" not in payload["matrix"]
    assert "developer" not in payload["matrix"]


async def test_put_rbac_allows_partial_matrix_for_manageable_roles(
    build_api_app,
    fake_db,
) -> None:
    async with await _client(build_api_app, current_user=_manager_user()) as client:
        response = await client.put(
            "/api/admin/rbac",
            json={
                "matrix": {
                    "employee": {
                        "media.view": False,
                        "media.delete": True,
                    }
                }
            },
        )

    assert response.status_code == 200
    assert fake_db.role_permissions["employee"]["media.delete"] is True
    assert fake_db.role_permissions["employee"]["media.view"] is True
    assert fake_db.role_permissions["manager"]["rbac.update"] is False


async def test_put_rbac_rejects_same_rank_role_updates(
    build_api_app,
) -> None:
    async with await _client(build_api_app, current_user=_manager_user()) as client:
        response = await client.put(
            "/api/admin/rbac",
            json={
                "matrix": {
                    "manager": {
                        "assistants.view": True,
                    }
                }
            },
        )

    assert response.status_code == 403
    assert "manager" in response.json()["detail"]


@pytest.mark.parametrize(
    "permission",
    [
        "rbac.update",
        "site.maintenance.update",
        "maintenance.bypass",
    ],
)
async def test_put_rbac_keeps_hidden_developer_safeguards(
    build_api_app,
    fake_db,
    permission: str,
) -> None:
    async with await _client(build_api_app, current_user=_manager_user()) as client:
        initial = await client.get("/api/admin/rbac")

    matrix = initial.json()["data"]["matrix"]
    for role_permissions in matrix.values():
        role_permissions[permission] = False

    async with await _client(build_api_app, current_user=_manager_user()) as client:
        response = await client.put(
            "/api/admin/rbac",
            json={"matrix": matrix},
        )

    assert response.status_code == 200
    assert fake_db.role_permissions["developer"][permission] is True
