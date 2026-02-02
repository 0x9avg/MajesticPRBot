"""
Monitoring and Dashboard routes for API.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from database import Database
    from services.broker import BrokerService

from config import Config
from fastapi import APIRouter, Depends, Request
from schemas.monitoring import MonitoringRefreshResponse

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


@router.post("/refresh", response_model=MonitoringRefreshResponse)
async def refresh_monitoring(
    data: MonitoringRefreshResponse,
    db: Annotated["Database", Depends(get_db)],
    broker: Annotated["BrokerService", Depends(get_broker)],
):
    """
    Trigger monitoring message refresh.
    Sends event to Discord bot to update monitoring embeds.
    """
    if broker:
        await broker.publish(
            "monitoring.refresh",
            {
                "event": "monitoring.refresh",
                "force": data.force,
            },
        )
        return {"status": "refresh_requested", "force": data.force}

    return {"status": "broker_unavailable"}
