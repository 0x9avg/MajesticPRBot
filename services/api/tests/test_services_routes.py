from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from routes.services import router as services_router
from runtime_status import record_service_heartbeat

pytestmark = pytest.mark.anyio


def _developer_user() -> dict:
    return {
        "id": 42,
        "username": "developer",
        "nickname": "Developer",
        "role": "developer",
        "principal_type": "user",
        "discord_id": 9042,
        "require_password_change": False,
        "permissions": {
            "monitoring.view": True,
            "media.status.update": True,
        },
    }


async def test_report_service_heartbeat_stores_service_status(build_api_app) -> None:
    app = build_api_app(
        services_router,
        current_service={
            "principal_type": "service",
            "service_name": "twitch_service",
            "permissions": {"media.status.update": True},
        },
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/services/heartbeat",
            json={"status": "online", "details": {"ready": True}},
        )

    assert response.status_code == 200
    assert response.json()["data"]["service_name"] == "twitch_service"
    assert app.state._service_registry["twitch_service"]["status"] == "online"


async def test_get_services_overview_returns_domain_and_runtime_state(
    build_api_app,
    fake_db,
) -> None:
    fake_db.service_overview_stats = {
        "streamers_total": 12,
        "streamers_online": 5,
        "gta_online": 3,
        "active_spec_sessions": 2,
        "probation_sessions": 1,
        "active_events": 4,
        "assistants_total": 8,
        "web_users_total": 6,
        "admin_actions_24h": 11,
    }
    app = build_api_app(
        services_router,
        current_user=_developer_user(),
    )
    record_service_heartbeat(
        app,
        "twitch_service",
        status="online",
        details={"tracked_streamers": 12},
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/services/overview")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["domain"]["streamers_total"] == 12
    assert data["api"]["status"] in {"healthy", "degraded"}
    twitch = next(
        item for item in data["services"] if item["service_name"] == "twitch_service"
    )
    assert twitch["status"] == "online"
    assert twitch["details"]["tracked_streamers"] == 12


async def test_trigger_twitch_sync_publishes_broker_event(
    build_api_app,
    fake_broker,
) -> None:
    app = build_api_app(
        services_router,
        include_broker=True,
        current_user=_developer_user(),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/services/twitch/sync")

    assert response.status_code == 202
    assert any(call[0] == "service.twitch.sync" for call in fake_broker.calls)


async def test_trigger_twitch_sync_returns_503_without_broker(build_api_app) -> None:
    app = build_api_app(
        services_router,
        include_broker=False,
        current_user=_developer_user(),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/services/twitch/sync")

    assert response.status_code == 503
    assert response.json()["code"] == "BROKER_UNAVAILABLE"
