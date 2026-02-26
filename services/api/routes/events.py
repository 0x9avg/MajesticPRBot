"""
Events routes for API.
Refactored to use envelope responses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database
    from services.broker import BrokerService

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from pydantic import BaseModel
from schemas.envelope import success_envelope
from schemas.event import EventCreate, EventJoinRequest, EventResponse

router = APIRouter(prefix="/events", tags=["Events"])


def get_db(request: Request):
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


@router.post("")
async def create_event(
    request: Request,
    data: EventCreate,
    db: "Database" = Depends(get_db),
):
    """Create a new event."""
    trace_id = get_trace_id(request)

    # Validate start_time is not in the past
    if data.start_time is not None:
        st = data.start_time
        if st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
        if st < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=400,
                detail="Время начала события не может быть в прошлом",
            )

    try:
        event_id = await db.create_event(
            name=data.name,
            description=data.description,
            channel_id=data.channel_id,
            message_id=0,
            created_by=data.created_by,
            required_pr_count=data.required_pr_count,
            start_time=data.start_time,
            notification_sent=(data.start_time is None),
            pr_slots=data.pr_slots,
            priority=data.priority,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not event_id:
        raise HTTPException(status_code=500, detail="Failed to create event")

    response_data = EventResponse(
        id=event_id,
        name=data.name,
        description=data.description,
        required_pr_count=data.required_pr_count,
        pr_slots=data.pr_slots,
        priority=data.priority,
        is_pinned=data.is_pinned,
        start_time=data.start_time,
        channel_id=data.channel_id,
        created_by=data.created_by,
        is_active=True,
        created_at=datetime.now(timezone.utc),
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


@router.get("")
async def get_all_events(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """Get all events (active and inactive)."""
    trace_id = get_trace_id(request)
    events = await db.get_all_events()

    return JSONResponse(
        content=success_envelope(
            data=[EventResponse(**e).model_dump(mode="json") for e in events],
            message=f"Found {len(events)} events",
            trace_id=trace_id,
        )
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
    broker: "BrokerService" = Depends(get_broker),
):
    """Join an event."""
    trace_id = get_trace_id(request)
    success = await db.join_event(event_id, data.user_id)

    if not success:
        raise HTTPException(
            status_code=400, detail="Could not join event (already joined or invalid)"
        )

    # Send broker notification
    if broker:
        event = await db.get_event(event_id)
        event_name = event.get("name", "Unknown") if event else "Unknown"
        await broker.emit_event_joined(
            event_id=event_id,
            event_name=event_name,
            pr_id=data.user_id,
            trace_id=trace_id,
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
    broker: "BrokerService" = Depends(get_broker),
):
    """Leave an event."""
    trace_id = get_trace_id(request)
    duration = await db.leave_event(event_id, data.user_id)

    # Send broker notification
    if broker:
        event = await db.get_event(event_id)
        event_name = event.get("name", "Unknown") if event else "Unknown"
        await broker.emit_event_left(
            event_id=event_id,
            event_name=event_name,
            pr_id=data.user_id,
            duration_seconds=duration or 0,
            trace_id=trace_id,
        )

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
    broker: "BrokerService" = Depends(get_broker),
):
    """End an event."""
    trace_id = get_trace_id(request)
    
    event = await db.get_event(event_id)
    event_name = event.get("name", "Unknown") if event else "Unknown"
    
    results = await db.end_event(event_id)

    if broker:
        for p in results:
            await broker.emit_event_left(
                event_id=event_id,
                event_name=event_name,
                pr_id=p["user_id"],
                duration_seconds=p.get("duration", 0),
                trace_id=trace_id,
            )

    return JSONResponse(
        content=success_envelope(
            data={"event_id": event_id, "participants": results},
            message="Event ended",
            code="EVENT_ENDED",
            trace_id=trace_id,
        )
    )


class EventUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    required_pr_count: Optional[int] = None
    priority: Optional[int] = None
    is_pinned: Optional[bool] = None
    points: Optional[float] = None


@router.patch("/{event_id}")
async def update_event(
    request: Request,
    event_id: int,
    data: EventUpdate,
    db: "Database" = Depends(get_db),
):
    """Update event details."""
    trace_id = get_trace_id(request)

    success = await db.update_event(
        event_id=event_id,
        name=data.name,
        description=data.description,
        required_pr_count=data.required_pr_count,
        priority=data.priority,
        is_pinned=data.is_pinned,
        points=data.points,
    )

    if not success:
        event = await db.get_event(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

    event = await db.get_event(event_id)

    return JSONResponse(
        content=success_envelope(
            data=event,
            message="Event updated",
            code="EVENT_UPDATED",
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
