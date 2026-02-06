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
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import success_envelope
from schemas.monitoring import MonitoringRefreshResponse

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


@router.post("/refresh")
async def refresh_monitoring(
    request: Request,
    data: MonitoringRefreshResponse,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
):
    """
    Trigger monitoring message refresh.
    Sends event to Discord bot to update monitoring embeds.
    """
    trace_id = get_trace_id(request)

    if broker:
        await broker.publish(
            "monitoring.refresh",
            {
                "event": "monitoring.refresh",
                "force": data.force,
            },
        )
        return JSONResponse(
            content=success_envelope(
                data={"force": data.force},
                message="Refresh requested",
                code="REFRESH_REQUESTED",
                trace_id=trace_id,
            )
        )

    return JSONResponse(
        status_code=503,
        content=success_envelope(
            data=None,
            message="Broker unavailable",
            code="BROKER_UNAVAILABLE",
            trace_id=trace_id,
        ),
    )


@router.get("/status")
async def get_monitoring_status(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """
    Get monitoring view model.
    Returns complete data for Discord bot to render monitoring message.
    """
    trace_id = get_trace_id(request)

    # Get all streamers
    streamers = await db.list_all_streamers()
    
    # Process streamer data
    online_streamers = []
    available_for_claim = []
    gta_count = 0
    total_count = len(streamers)
    
    gta5_game_id = Config.gta5_game_id
    
    for s in streamers:
        if s.get("is_online"):
            is_gta = str(s.get("game_id")) == gta5_game_id
            
            online_streamers.append({
                "streamer_id": s["streamer_id"],
                "streamer_name": s["streamer_name"],
                "game_id": s.get("game_id"),
                "game_name": s.get("game_name"),
                "stream_title": s.get("stream_title"),
                "stream_thumbnail_url": s.get("stream_thumbnail_url"),
                "started_at": s.get("started_at"),
                "is_gta": is_gta,
                "priority": s.get("priority", 3),
                "assignments": s.get("assignments", []),
            })
            
            if is_gta:
                gta_count += 1
                
                # Check slot availability (Max 2: Main + Probation)
                assignments = s.get("assignments", [])
                has_main = False
                has_probation = False
                
                for a in assignments:
                    if a.get("is_probation"):
                        has_probation = True
                    else:
                        has_main = True
                
                # Available if either slot is free
                # Note: This list feeds the dropdown.
                # Ideally we show if ANY slot is free.
                if not (has_main and has_probation):
                    available_for_claim.append({
                        "streamer_id": s["streamer_id"],
                        "streamer_name": s["streamer_name"],
                        "priority": s.get("priority", 3),
                        "has_main": has_main,
                        "has_probation": has_probation
                    })
    
    # Sort by priority (P0 first)
    online_streamers.sort(key=lambda x: x["priority"])
    available_for_claim.sort(key=lambda x: x["priority"])
    
    return JSONResponse(
        content=success_envelope(
            data={
                "total_streamers": total_count,
                "online_count": len(online_streamers),
                "gta_count": gta_count,
                "available_count": len(available_for_claim),
                "online_streamers": online_streamers,
                "available_for_claim": available_for_claim,
            },
            message="Monitoring status",
            trace_id=trace_id,
        )
    )

