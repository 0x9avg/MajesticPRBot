"""Monitoring routes for on-demand Discord monitoring views."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db import Database

from config import Config
from dependencies import require_permission
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import success_envelope

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


@router.get("/status")
async def get_monitoring_status(
    request: Request,
    db: "Database" = Depends(get_db),
    _principal: dict = Depends(require_permission("monitoring.view")),
):
    """
    Get monitoring view model.
    Returns complete data for Discord bot to render monitoring message.
    """
    trace_id = get_trace_id(request)

    # Get all online streamers with assignments
    streamers = await db.list_online_streamers()
    events = await db.get_active_events()

    # Process streamer data
    online_streamers = []
    available_for_claim = []
    gta_count = 0
    total_count = len(streamers)

    gta5_game_id = Config.gta5_game_id

    for s in streamers:
        if s.get("is_online"):
            is_gta = str(s.get("game_id")) == gta5_game_id

            online_streamers.append(
                {
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
                }
            )

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
                if not (has_main and has_probation):
                    available_for_claim.append(
                        {
                            "streamer_id": s["streamer_id"],
                            "streamer_name": s["streamer_name"],
                            "priority": s.get("priority", 3),
                            "has_main": has_main,
                            "has_probation": has_probation,
                        }
                    )

    # Process events for claim dropdown
    active_events = []
    for e in events:
        active_events.append({
            "is_event": True,
            "event_id": e["id"],
            "name": e["name"],
            "description": e.get("description"),
            "start_time": e.get("start_time"),
            "current_participants": e.get("current_participants", 0),
            "participants": e.get("participants", []),
            "pr_slots": e.get("pr_slots", e.get("required_pr_count", 1)),
            "is_pinned": e.get("is_pinned", False),
            "priority": e.get("priority", 0)
        })

        if e.get("current_participants", 0) < e.get("pr_slots", e.get("required_pr_count", 1)):
            available_for_claim.append(
                {
                    "is_event": True,
                    "event_id": e["id"],
                    "streamer_name": f"[Событие] {e['name']}",
                    "priority": e.get("priority", 0),
                    "is_pinned": e.get("is_pinned", False),
                    "has_main": True,
                    "has_probation": False
                }
            )

    # Sort streamers by priority (P0 first)
    online_streamers.sort(key=lambda x: x["priority"])
    # Sort claimable items by pinning and priority
    available_for_claim.sort(key=lambda x: (not x.get("is_pinned", False), x["priority"]))

    return JSONResponse(
        content=success_envelope(
            data={
                "total_streamers": total_count,
                "online_count": len(online_streamers),
                "gta_count": gta_count,
                "available_count": len(available_for_claim),
                "online_streamers": online_streamers,
                "active_events": active_events,
                "available_for_claim": available_for_claim,
            },
            message="Monitoring status",
            trace_id=trace_id,
        )
    )
