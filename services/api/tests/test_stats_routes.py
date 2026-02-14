from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from routes.stats import router as stats_router

pytestmark = pytest.mark.anyio


async def test_get_dashboard_stats(build_api_app, fake_db) -> None:
    fake_db.dashboard_stats = {
        "assigned_pr_count": 7,
        "unassigned_media_count": 2,
        "events_today_count": 3,
    }

    app = build_api_app(stats_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/stats/dashboard")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["assigned_pr_count"] == 7
    assert data["unassigned_media_count"] == 2
    assert data["events_today_count"] == 3
