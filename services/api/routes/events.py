"""
Events routes for API.
Refactored to use envelope responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, List

if TYPE_CHECKING:
    from database import Database

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import success_envelope
from schemas.event import EventCreate, EventEndResponse, EventJoinRequest, EventResponse

router = APIRouter(prefix="/events", tags=["Events"])


def get_db(request: Request):
    return request.app.state.database


@router.post("")
async def create_event(
    request: Request,
    data: EventCreate,
    db: "Database" = Depends(get_db),
):
    """Create a new event."""
    trace_id = get_trace_id(request)

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

    response_data = EventResponse(
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

    return JSONResponse(
        status_code=201,
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message=f"Event '{data.name}' created",
            code="EVENT_CREATED",
            trace_id=trace_id,
        ),
    )


@router.get("/active")
async def get_active_events(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """Get active events for a guild."""
    trace_id = get_trace_id(request)
    events = await db.get_active_events()

    return JSONResponse(
        content=success_envelope(
            data=[EventResponse(**e).model_dump(mode="json") for e in events],
            message=f"Found {len(events)} active events",
            trace_id=trace_id,
        )
    )


@router.get("/scheduled")
async def get_events_to_start(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """Get events that need start notification."""
    trace_id = get_trace_id(request)
    events = await db.get_scheduled_events()

    return JSONResponse(
        content=success_envelope(
            data=events,
            message=f"Found {len(events)} scheduled events",
            trace_id=trace_id,
        )
    )


@router.get("/user/{user_id}/active")
async def get_user_active_event(
    request: Request,
    user_id: int,
    db: "Database" = Depends(get_db),
):
    """Check if user is in an active event."""
    trace_id = get_trace_id(request)
    result = await db.get_user_active_event_participation(user_id)

    return JSONResponse(
        content=success_envelope(
            data=result,
            message="User event participation status",
            trace_id=trace_id,
        )
    )


@router.get("/{event_id}")
async def get_event(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
):
    """Get a specific event by ID."""
    trace_id = get_trace_id(request)
    event = await db.get_event(event_id)

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return JSONResponse(
        content=success_envelope(
            data=event,
            message="Event found",
            trace_id=trace_id,
        )
    )


@router.get("/{event_id}/participants")
async def get_event_participants(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
):
    """Get event participants."""
    trace_id = get_trace_id(request)
    participants = await db.get_event_participants(event_id)

    return JSONResponse(
        content=success_envelope(
            data=participants,
            message=f"Found {len(participants)} participants",
            trace_id=trace_id,
        )
    )


@router.post("/{event_id}/join")
async def join_event(
    request: Request,
    event_id: int,
    data: EventJoinRequest,
    db: "Database" = Depends(get_db),
):
    """Join an event."""
    trace_id = get_trace_id(request)
    success = await db.join_event(event_id, data.user_id)

    if not success:
        raise HTTPException(
            status_code=400, detail="Could not join event (already joined or invalid)"
        )

    return JSONResponse(
        content=success_envelope(
            data={"event_id": event_id, "user_id": data.user_id},
            message="Joined event",
            code="EVENT_JOINED",
            trace_id=trace_id,
        )
    )


@router.post("/{event_id}/leave")
async def leave_event(
    request: Request,
    event_id: int,
    data: EventJoinRequest,
    db: "Database" = Depends(get_db),
):
    """Leave an event."""
    trace_id = get_trace_id(request)
    duration = await db.leave_event(event_id, data.user_id)

    return JSONResponse(
        content=success_envelope(
            data={"event_id": event_id, "user_id": data.user_id, "duration": duration},
            message="Left event",
            code="EVENT_LEFT",
            trace_id=trace_id,
        )
    )


@router.post("/{event_id}/end")
async def end_event(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
):
    """End an event."""
    trace_id = get_trace_id(request)
    results = await db.end_event(event_id)

    return JSONResponse(
        content=success_envelope(
            data={"event_id": event_id, "participants": results},
            message="Event ended",
            code="EVENT_ENDED",
            trace_id=trace_id,
        )
    )


@router.patch("/{event_id}/notification-sent")
async def mark_notification_sent(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
):
    """Mark event notification as sent."""
    trace_id = get_trace_id(request)
    await db.mark_event_notification_sent(event_id)

    return JSONResponse(
        content=success_envelope(
            data={"event_id": event_id},
            message="Notification marked as sent",
            code="NOTIFICATION_MARKED",
            trace_id=trace_id,
        )
    )


@router.patch("/{event_id}/message")
async def update_event_message(
    request: Request,
    event_id: int,
    message_id: int,
    db: "Database" = Depends(get_db),
):
    """Update event message ID."""
    trace_id = get_trace_id(request)
    await db.update_event_message_id(event_id, message_id)

    return JSONResponse(
        content=success_envelope(
            data={"event_id": event_id, "message_id": message_id},
            message="Event message ID updated",
            code="MESSAGE_UPDATED",
            trace_id=trace_id,
        )
    )
