"""
Notification rendering routes for API.
Provides pre-rendered notification messages for Discord bot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Optional

if TYPE_CHECKING:
    from database import Database

from config import Config
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import success_envelope

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


# Default templates
DEFAULT_TEMPLATES = {
    "stream_online": "**{streamer_name}** начал стрим!",
    "stream_offline": "**{streamer_name}** закончил стрим.",
    "category_to_gta": "🎮 **{streamer_name}** переключился на GTA 5!",
    "category_from_gta": "📴 **{streamer_name}** вышел из GTA 5.",
}


def format_template(
    template: str,
    streamer_name: str,
    stream_title: str = "",
    game_name: str = "",
) -> str:
    """Format notification template with streamer data."""
    streamer_link = f"https://twitch.tv/{streamer_name.lower()}"
    
    return template.format(
        streamer_name=streamer_name,
        stream_title=stream_title or "",
        game_name=game_name or "",
        streamer_link=streamer_link,
    )


@router.get("/render/{event_type}")
async def render_notification(
    request: Request,
    event_type: str,
    streamer_id: int = Query(..., description="Streamer ID"),
    db: "Database" = Depends(get_db),
):
    """
    Render a notification message for the given event type and streamer.
    Returns the formatted message and component spec for Discord.
    """
    trace_id = get_trace_id(request)
    
    # Validate event type
    valid_types = ["stream_online", "stream_offline", "category_to_gta", "category_from_gta"]
    if event_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid event type. Must be one of: {valid_types}")
    
    # Get streamer data
    streamer = await db.get_streamer(streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Streamer not found")
    
    # Get guild settings for template
    settings = await db.get_guild()
    if not settings:
        raise HTTPException(status_code=404, detail="Guild settings not found")
    
    # Get template (from settings or default)
    template = settings.get(f"template_{event_type}") or DEFAULT_TEMPLATES.get(event_type, "")
    
    if not template:
        raise HTTPException(status_code=404, detail=f"No template found for {event_type}")
    
    # Format message
    streamer_name = streamer.get("streamer_name", "Unknown")
    stream_title = streamer.get("stream_title", "")
    game_name = streamer.get("game_name", "")
    thumbnail_url = streamer.get("stream_thumbnail_url", "")
    
    formatted_message = format_template(template, streamer_name, stream_title, game_name)
    
    # Determine if claim button should be shown
    is_gta = str(streamer.get("game_id")) == Config.gta5_game_id
    show_claim_button = is_gta and event_type in ["stream_online", "category_to_gta"]
    
    # Build component spec (Discord bot will interpret this)
    component_spec = {
        "type": "notification",
        "streamer_id": streamer_id,
        "streamer_name": streamer_name,
        "stream_title": stream_title,
        "game_name": game_name,
        "thumbnail_url": thumbnail_url,
        "show_claim_button": show_claim_button,
        "assigned_pr_id": streamer.get("assigned_pr_id"),
    }
    
    return JSONResponse(
        content=success_envelope(
            data={
                "event_type": event_type,
                "message": formatted_message,
                "component_spec": component_spec,
                "notification_channel_id": settings.get("notification_channel_id"),
            },
            message=f"Notification rendered for {event_type}",
            trace_id=trace_id,
        )
    )


@router.get("/channel")
async def get_notification_channel(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """Get the configured notification channel ID."""
    trace_id = get_trace_id(request)
    
    settings = await db.get_guild()
    if not settings:
        raise HTTPException(status_code=404, detail="Guild settings not found")
    
    return JSONResponse(
        content=success_envelope(
            data={"notification_channel_id": settings.get("notification_channel_id")},
            message="Notification channel",
            trace_id=trace_id,
        )
    )
