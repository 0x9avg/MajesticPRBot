from __future__ import annotations

from copy import deepcopy

import pytest
from httpx import ASGITransport, AsyncClient

from routes.game_servers import router as game_servers_router

pytestmark = pytest.mark.anyio


async def _client(build_api_app):
    app = build_api_app(game_servers_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_public_game_servers_catalog_returns_all_seeded_rows(build_api_app) -> None:
    async with await _client(build_api_app) as client:
        response = await client.get("/api/game-servers")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert len(payload) == 18
    assert payload[0]["id"] == 1
    assert payload[0]["full_name"] == "Majestic #1"
    assert payload[0]["short_name"] == "#1"
    assert payload[0]["command_name"] == "RU1"


async def test_game_servers_catalog_allows_game_servers_view_without_dashboard_view(
    build_api_app,
    default_current_user,
) -> None:
    current_user = deepcopy(default_current_user)
    current_user["permissions"]["dashboard.view"] = False
    current_user["permissions"]["game_servers.view"] = True

    app = build_api_app(game_servers_router, current_user=current_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/game-servers")

    assert response.status_code == 200


async def test_game_servers_catalog_allows_game_servers_view_without_dashboard_view_via_settings_scope(
    build_api_app,
    default_current_user,
) -> None:
    current_user = deepcopy(default_current_user)
    current_user["permissions"]["dashboard.view"] = False
    current_user["permissions"]["game_servers.view"] = True
    current_user["permissions"]["game_servers.settings.view"] = True
    current_user["permissions"]["game_servers.settings.update"] = True

    app = build_api_app(game_servers_router, current_user=current_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/game-servers")

    assert response.status_code == 200


async def test_game_servers_catalog_rejects_without_read_permissions(
    build_api_app,
    default_current_user,
) -> None:
    current_user = deepcopy(default_current_user)
    current_user["permissions"]["dashboard.view"] = False
    current_user["permissions"]["game_servers.view"] = False
    current_user["permissions"]["game_servers.settings.view"] = False
    current_user["permissions"]["game_servers.settings.update"] = False

    app = build_api_app(game_servers_router, current_user=current_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/game-servers")

    assert response.status_code == 403
