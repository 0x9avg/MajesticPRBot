"""
Events routes for API.
Refactored to use database methods.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Annotated, List, Optional

if TYPE_CHECKING:
    from database import Database

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from datetime import datetime

from schemas.event import EventCreate, EventResponse, EventJoinRequest, EventEndResponse

router = APIRouter(prefix="/events", tags=["Events"])


def get_db(request: Request):
    return request.app.state.database


@router.post("", response_model=EventResponse)
async def create_event(data: EventCreate, db: Annotated["Database", Depends(get_db)]):
    """Create a new event."""
    event_id = await db.create_event(
        name=data.name,
        description=data.description,
        channel_id=data.channel_id,
        message_id=0,  # Placeholder, updated later by bot
        created_by=data.created_by,
        required_pr_count=data.required_pr_count,
        start_time=data.start_time,
        notification_sent=(data.start_time is None),  # True if immediate
    )

    if not event_id:
        raise HTTPException(status_code=500, detail="Failed to create event")

    return EventResponse(
        id=event_id,
        name=data.name,
        description=data.description,
        required_pr_count=data.required_pr_count,
        start_time=data.start_time,
        channel_id=data.channel_id,
        created_by=data.created_by,
        is_active=True,
        created_at=datetime.utcnow(),
        notification_sent=(data.start_time is None),
    )


@router.get("/active", response_model=List[EventResponse])
async def get_active_events(db: Annotated["Database", Depends(get_db)]):
    """Get active events for a guild."""
    events = await db.get_active_events()
    return [EventResponse(**e) for e in events]


@router.get("/scheduled")
async def get_events_to_start(db: Annotated["Database", Depends(get_db)]):
    """Get events that need start notification."""
    return await db.get_scheduled_events()


@router.get("/user/{user_id}/active")
async def get_user_active_event(
    user_id: int, db: Annotated["Database", Depends(get_db)]
):
    """Check if user is in an active event."""
    return await db.get_user_active_event_participation(user_id)


@router.get("/{event_id}")
async def get_event(event_id: int, db: Annotated["Database", Depends(get_db)]):
    """Get a specific event by ID."""
    event = await db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/{event_id}/participants")
async def get_event_participants(
    event_id: int, db: Annotated["Database", Depends(get_db)]
):
    """Get event participants."""
    return await db.get_event_participants(event_id)


@router.post("/{event_id}/join")
async def join_event(
    event_id: int, data: EventJoinRequest, db: Annotated["Database", Depends(get_db)]
):
    """Join an event."""
    success = await db.join_event(event_id, data.user_id)
    if not success:
        raise HTTPException(
            status_code=400, detail="Could not join event (already joined or invalid)"
        )
    return {"status": "joined"}


@router.post("/{event_id}/leave")
async def leave_event(
    event_id: int, data: EventJoinRequest, db: Annotated["Database", Depends(get_db)]
):
    """Leave an event."""
    duration = await db.leave_event(event_id, data.user_id)
    return {"status": "left", "duration": duration}


@router.post("/{event_id}/end")
async def end_event(event_id: int, db: Annotated["Database", Depends(get_db)]):
    """End an event."""
    results = await db.end_event(event_id)
    return {"status": "ended", "event_id": event_id, "participants": results}


@router.patch("/{event_id}/notification-sent")
async def mark_notification_sent(
    event_id: int, db: Annotated["Database", Depends(get_db)]
):
    """Mark event notification as sent."""
    await db.mark_event_notification_sent(event_id)
    return {"status": "updated"}


@router.patch("/{event_id}/message")
async def update_event_message(
    event_id: int, message_id: int, db: Annotated["Database", Depends(get_db)]
):
    """Update event message ID."""
    await db.update_event_message_id(event_id, message_id)
    return {"status": "updated"}
