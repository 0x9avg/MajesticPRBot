"""
Events routes for API.
Refactored to use envelope responses.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

# Moscow timezone (UTC+3)
MSK = timezone(timedelta(hours=3))
if TYPE_CHECKING:
    from database import Database
    from services.broker import BrokerService

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from pydantic import BaseModel
from schemas.envelope import success_envelope
from schemas.event import (
    EventCreate,
    EventResponse,
    SpecRequestCreate,
    SpecRequestUpdate,
)
from dependencies import require_permission

router = APIRouter(prefix="/events", tags=["Events"])


def get_db(request: Request):
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


def _resolve_user_pr_id(principal: dict) -> int:
    discord_id = principal.get("discord_id")
    if discord_id is None:
        raise HTTPException(status_code=400, detail="User has no discord_id")
    try:
        return int(discord_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid discord_id")


def _resolve_actor_id(principal: dict) -> int:
    """Resolve immutable actor ID for audit fields from auth principal."""
    if principal.get("principal_type") == "service":
        return 0
    return _resolve_user_pr_id(principal)


def _serialize_event_participant(participant: dict) -> dict:
    result = dict(participant)
    if result.get("pr_id") is not None:
        result["pr_id"] = str(result["pr_id"])
    return result


@router.post("")
async def create_event(
    request: Request,
    data: EventCreate,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    principal: dict = Depends(require_permission("events.create")),
):
    """Create a new event."""
    trace_id = get_trace_id(request)

    # Validate start_time is not in the past
    if data.start_time is not None:
        st = data.start_time
        if st.tzinfo is None:
            # Assumes native datetime is MSK. This converts it to an aware MSK datetime object!
            st = st.replace(tzinfo=MSK)
            data.start_time = st
        if st < datetime.now(MSK):
            raise HTTPException(
                status_code=400,
                detail="Время начала события не может быть в прошлом",
            )

    created_by = _resolve_actor_id(principal)

    try:
        event_id = await db.create_event(
            name=data.name,
            description=data.description,
            created_by=created_by,
            required_pr_count=data.required_pr_count,
            start_time=data.start_time,
            notification_sent=(data.start_time is None),
            pr_slots=data.pr_slots,
            priority=data.priority,
            is_pinned=data.is_pinned,
            outbox_trace_id=trace_id,
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
        created_by=created_by,
        is_active=True,
        created_at=datetime.now(MSK),
        notification_sent=(data.start_time is None),
    )

    actor_name = principal.get("nickname") or principal.get("username")
    if principal.get("principal_type") == "service":
        actor_name = f"service:{principal.get('service_name', 'unknown')}"
    await db.log_admin_action_v2(
        actor_name=actor_name or "Unknown",
        actor_role=(
            principal.get("role")
            if principal.get("principal_type") == "user"
            else "service"
        ),
        action="event.create",
        target_type="event",
        target_id=str(event_id),
        details={
            "summary": f"Created event {data.name}",
            "changes": {
                "after": {
                    "name": data.name,
                    "description": data.description,
                    "required_pr_count": data.required_pr_count,
                    "pr_slots": data.pr_slots,
                    "priority": data.priority,
                    "start_time": (
                        data.start_time.isoformat() if data.start_time else None
                    ),
                }
            },
            "meta": {
                "ip": request.client.host if request.client else None,
                "request_path": str(request.url.path),
                "method": request.method,
                "actor_id": created_by,
                "principal_type": principal.get("principal_type"),
                "service_name": (
                    principal.get("service_name")
                    if principal.get("principal_type") == "service"
                    else None
                ),
            },
        },
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
    _principal: dict = Depends(require_permission("events.view")),
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
    _principal: dict = Depends(require_permission("events.view")),
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
    _principal: dict = Depends(require_permission("events.manage")),
):
    """Get events that need start notification."""
    trace_id = get_trace_id(request)
    events = await db.get_scheduled_events()
    normalized_events = []
    for event in events:
        item = dict(event)
        item["participants"] = [
            _serialize_event_participant(participant)
            for participant in item.get("participants", [])
        ]
        normalized_events.append(item)

    return JSONResponse(
        content=success_envelope(
            data=normalized_events,
            message=f"Found {len(normalized_events)} scheduled events",
            trace_id=trace_id,
        )
    )


@router.post("/spec-request")
async def create_spec_request(
    request: Request,
    data: SpecRequestCreate,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    user: dict = Depends(require_permission("events.spec.request")),
):
    """Create a spec request event (pending approval) and auto-join."""
    trace_id = get_trace_id(request)
    pr_id = user.get("discord_id")
    if not pr_id:
        raise HTTPException(status_code=400, detail="User has no discord_id")

    try:
        event_id = await db.create_spec_request(
            name=data.name,
            description=data.description,
            requested_by=pr_id,
            priority=data.priority,
            outbox_trace_id=trace_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not event_id:
        raise HTTPException(status_code=500, detail="Failed to create spec request")

    return JSONResponse(
        status_code=201,
        content=success_envelope(
            data={"event_id": event_id},
            message="Spec request created",
            code="SPEC_REQUEST_CREATED",
            trace_id=trace_id,
        ),
    )


@router.get("/pending")
async def get_pending_spec_requests(
    request: Request,
    db: "Database" = Depends(get_db),
    user: dict = Depends(require_permission("events.spec.manage")),
):
    """Get pending spec requests for admin review."""
    trace_id = get_trace_id(request)
    requests_list = await db.get_pending_spec_requests()

    for req in requests_list:
        if req.get("id"):
            req["id"] = str(req["id"])
        if req.get("requested_by"):
            req["requested_by"] = str(req["requested_by"])

    return JSONResponse(
        content=success_envelope(
            data=requests_list,
            message=f"Found {len(requests_list)} pending spec requests",
            trace_id=trace_id,
        )
    )


@router.patch("/{event_id}/pending")
async def update_pending_spec_request(
    request: Request,
    event_id: int,
    data: SpecRequestUpdate,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    user: dict = Depends(require_permission("events.spec.manage")),
):
    """Update a pending spec request without approving it."""
    trace_id = get_trace_id(request)

    # Check permission or just assume admin if they hit this route (depends on your auth flow)
    # usually /events/pending handles are admin only, enforced by middleware

    try:
        success = await db.update_pending_spec_request(
            event_id=event_id,
            name=data.name,
            description=data.description,
            priority=data.priority,
            start_time=(
                data.start_time.strftime("%Y-%m-%d %H:%M:%S")
                if data.start_time
                else None
            ),
            end_time=(
                data.end_time.strftime("%Y-%m-%d %H:%M:%S") if data.end_time else None
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not success:
        raise HTTPException(
            status_code=500, detail="Failed to update pending spec request"
        )

    return JSONResponse(
        content=success_envelope(
            data={"event_id": event_id, "status": "updated"},
            message="Spec request updated",
            code="SPEC_REQUEST_UPDATED",
            trace_id=trace_id,
        )
    )


@router.post("/{event_id}/approve")
async def approve_spec_request(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    user: dict = Depends(require_permission("events.spec.manage")),
):
    """Approve a pending spec request."""
    trace_id = get_trace_id(request)
    approved_by = user.get("discord_id")
    if not approved_by:
        raise HTTPException(status_code=400, detail="User has no discord_id")

    try:
        result = await db.approve_spec_request(
            event_id=event_id,
            approved_by=approved_by,
            outbox_trace_id=trace_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not result or not result.get("success"):
        raise HTTPException(status_code=500, detail="Failed to approve spec request")

    return JSONResponse(
        content=success_envelope(
            data={"event_id": event_id, "status": "approved"},
            message="Spec request approved",
            code="SPEC_REQUEST_APPROVED",
            trace_id=trace_id,
        )
    )


@router.post("/{event_id}/reject")
async def reject_spec_request(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    user: dict = Depends(require_permission("events.spec.manage")),
):
    """Reject a pending spec request."""
    trace_id = get_trace_id(request)
    rejected_by = user.get("discord_id")
    if not rejected_by:
        raise HTTPException(status_code=400, detail="User has no discord_id")

    try:
        success = await db.reject_spec_request(
            event_id=event_id,
            rejected_by=rejected_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not success:
        raise HTTPException(status_code=500, detail="Failed to reject spec request")

    return JSONResponse(
        content=success_envelope(
            data={"event_id": event_id, "status": "rejected"},
            message="Spec request rejected",
            code="SPEC_REQUEST_REJECTED",
            trace_id=trace_id,
        )
    )


@router.get("/{event_id}")
async def get_event(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
    _principal: dict = Depends(require_permission("events.view")),
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
    _principal: dict = Depends(require_permission("events.view")),
):
    """Get event participants."""
    trace_id = get_trace_id(request)
    participants = await db.get_event_participants(event_id)

    return JSONResponse(
        content=success_envelope(
            data=[_serialize_event_participant(participant) for participant in participants],
            message=f"Found {len(participants)} participants",
            trace_id=trace_id,
        )
    )


async def _join_event_for_pr(
    request: Request,
    event_id: int,
    pr_id: int,
    db: "Database",
    broker: "BrokerService",
) -> JSONResponse:
    trace_id = get_trace_id(request)
    result = await db.join_event(
        event_id,
        pr_id,
        outbox_trace_id=trace_id,
    )
    if not result or result.get("status") == "error":
        detail = (
            result.get("detail", "Could not join event")
            if result
            else "Could not join event"
        )
        raise HTTPException(status_code=400, detail=detail)

    join_status = result.get("status")
    return JSONResponse(
        content=success_envelope(
            data={"event_id": str(event_id), "pr_id": str(pr_id), "join_status": join_status},
            message="Joined event" if join_status == "joined" else "Reserved slot",
            code="EVENT_JOINED" if join_status == "joined" else "EVENT_RESERVED",
            trace_id=trace_id,
        )
    )


async def _leave_event_for_pr(
    request: Request,
    event_id: int,
    pr_id: int,
    db: "Database",
    broker: "BrokerService",
) -> JSONResponse:
    trace_id = get_trace_id(request)
    duration = await db.leave_event(
        event_id,
        pr_id,
        end_reason="manual_unclaim",
        outbox_trace_id=trace_id,
    )

    return JSONResponse(
        content=success_envelope(
            data={"event_id": str(event_id), "pr_id": str(pr_id), "duration": duration},
            message="Left event",
            code="EVENT_LEFT",
            trace_id=trace_id,
        )
    )


@router.post("/{event_id}/join")
async def join_event(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    principal: dict = Depends(require_permission("events.join.self")),
):
    """Join an event as the current authenticated user."""
    if principal.get("principal_type") != "user":
        raise HTTPException(
            status_code=403,
            detail="Service principal must use /api/events/{event_id}/join/{pr_id}",
        )
    pr_id = _resolve_user_pr_id(principal)
    return await _join_event_for_pr(request, event_id, pr_id, db, broker)


@router.post("/{event_id}/join/{pr_id}")
async def join_event_for_pr(
    request: Request,
    event_id: int,
    pr_id: int,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    _principal: dict = Depends(require_permission("events.manage")),
):
    """Service/admin join flow for a target PR ID."""
    return await _join_event_for_pr(request, event_id, pr_id, db, broker)


@router.post("/{event_id}/leave")
async def leave_event(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    principal: dict = Depends(require_permission("events.leave.self")),
):
    """Leave an event as the current authenticated user."""
    if principal.get("principal_type") != "user":
        raise HTTPException(
            status_code=403,
            detail="Service principal must use /api/events/{event_id}/leave/{pr_id}",
        )
    pr_id = _resolve_user_pr_id(principal)
    return await _leave_event_for_pr(request, event_id, pr_id, db, broker)


@router.post("/{event_id}/leave/{pr_id}")
async def leave_event_for_pr(
    request: Request,
    event_id: int,
    pr_id: int,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    _principal: dict = Depends(require_permission("events.leave.any")),
):
    """Service/admin leave flow for a target PR ID."""
    return await _leave_event_for_pr(request, event_id, pr_id, db, broker)


@router.post("/{event_id}/start")
async def start_event(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    _principal: dict = Depends(require_permission("events.manage")),
):
    """Start an event and migrate its reserved participants to active sessions."""
    trace_id = get_trace_id(request)

    if not await db.get_event(event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    migrated_pr_ids = await db.start_event_sessions(
        event_id,
        outbox_trace_id=trace_id,
    )

    return JSONResponse(
        content=success_envelope(
            data={
                "event_id": event_id,
                "migrated_count": len(migrated_pr_ids),
                "migrated_pr_ids": migrated_pr_ids,
            },
            message="Event started and participants migrated",
            code="EVENT_STARTED",
            trace_id=trace_id,
        )
    )


@router.post("/{event_id}/end")
async def end_event(
    request: Request,
    event_id: int,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    _principal: dict = Depends(require_permission("events.manage")),
):
    """End an event."""
    trace_id = get_trace_id(request)

    results = await db.end_event(
        event_id,
        outbox_trace_id=trace_id,
    )

    return JSONResponse(
        content=success_envelope(
            data={
                "event_id": str(event_id),
                "participants": [
                    {"pr_id": str(item["pr_id"]), "duration": item.get("duration", 0)}
                    for item in results
                ],
            },
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
    broker: "BrokerService" = Depends(get_broker),
    _principal: dict = Depends(require_permission("events.update")),
):
    """Update event details."""
    trace_id = get_trace_id(request)

    # Block pr_slots/required_pr_count changes for spec_request events
    event_check = await db.get_event(event_id)
    if event_check and event_check.get("event_kind") == "spec_request":
        data.required_pr_count = None

    success = await db.update_event(
        event_id=event_id,
        name=data.name,
        description=data.description,
        required_pr_count=data.required_pr_count,
        priority=data.priority,
        is_pinned=data.is_pinned,
        points=data.points,
        outbox_trace_id=trace_id,
    )

    # Retroactive update: propagate priority changes to active sessions on this event
    if data.priority is not None:
        await db.recalc_target_active_sessions(
            target_type="event",
            target_id=event_id,
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
    _principal: dict = Depends(require_permission("events.manage")),
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
