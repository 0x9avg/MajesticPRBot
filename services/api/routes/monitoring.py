"""
Monitoring and Dashboard routes for API.
"""

from fastapi import APIRouter, Depends, Request

from schemas.monitoring import MonitoringRefreshRequest
from config import Config

router = APIRouter(tags=["Monitoring"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


@router.post("/monitoring/refresh")
async def refresh_monitoring(
    data: MonitoringRefreshRequest = MonitoringRefreshRequest(),
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """
    Trigger monitoring message refresh.
    Sends event to Discord bot to update monitoring embeds.
    """
    if broker:
        await broker.publish("monitoring.refresh", {
            "event": "monitoring.refresh",
            "guild_id": Config.GUILD_ID,
            "force": data.force,
        })
        return {"status": "refresh_requested", "force": data.force}
    
    return {"status": "broker_unavailable"}
