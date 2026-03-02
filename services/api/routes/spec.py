"""
Spec system routes for API.
Claim/unclaim/transfer streamers for PR assistants.
Refactored to use envelope responses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database
    from services.broker import BrokerService

from config import Config
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.spec import (
    SpecClaimRequest,
    SpecSessionResponse,
    SpecUnclaimRequest,
)
from schemas.enums import SpecSessionEndReason
from schemas.envelope import success_envelope

router = APIRouter(prefix="/spec", tags=["Spec System"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker




@router.post("/claim")
async def claim_streamer(
    request: Request,
    data: SpecClaimRequest,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
):
    """Claim a streamer for a PR assistant (supports Probation Slot Logic)."""
    trace_id = get_trace_id(request)

    # Check if streamer exists
    streamer = await db.get_streamer(data.streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    # Check if streamer is online
    if not streamer.get("is_online"):
        raise HTTPException(status_code=400, detail="Стример в оффлайне")

    # Check if streamer is in GTA 5 category
    if str(streamer.get("game_id")) != Config.gta5_game_id:
        raise HTTPException(status_code=400, detail="Стример не в категории GTA 5")

    # Check if junior is allowed to claim this streamer
    if data.is_probation and not streamer.get("allow_juniors", True):
        raise HTTPException(
            status_code=403,
            detail="Стажерам запрещено закрепляться за этим стримером",
        )

    # Check if PR already has an active spec session (streamer or event)
    current = await db.get_pr_current_streamer(data.pr_id)
    if current:
        raise HTTPException(
            status_code=409,
            detail=f"Вы уже закреплены за стримером {current['streamer_name']}",
        )

    # Also check active event participation
    active_event = await db.get_user_active_event_participation(data.pr_id)
    if active_event:
        raise HTTPException(
            status_code=409,
            detail=f"У вас уже есть активный спек на событие «{active_event['name']}»",
        )

    assignments = streamer.get("assignments", [])
    requested_slot = "Probation" if data.is_probation else "Main"
    for assignment in assignments:
        if assignment.get("is_probation") == data.is_probation:
            raise HTTPException(
                status_code=409,
                detail=f"Слот {requested_slot} уже занят @{assignment.get('nickname', assignment['pr_id'])}",
            )
    try:
        await db.assign_pr_to_streamer(
            data.streamer_id, data.pr_id, is_probation=data.is_probation
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if broker:
        await broker.emit_spec_claimed(
            data.streamer_id,
            streamer["streamer_name"],
            data.pr_id,
            data={"is_probation": data.is_probation},
            trace_id=trace_id,
        )

    return JSONResponse(
        content=success_envelope(
            data={
                "streamer_id": data.streamer_id,
                "streamer_name": streamer["streamer_name"],
                "pr_id": data.pr_id,
                "is_probation": data.is_probation,
            },
            message=f"Claimed {streamer['streamer_name']}",
            code="SPEC_CLAIMED",
            trace_id=trace_id,
        )
    )


@router.post("/unclaim")
async def unclaim_streamer(
    request: Request,
    data: SpecUnclaimRequest,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
):
    """Unclaim a streamer."""
    trace_id = get_trace_id(request)

    streamer = await db.get_streamer(data.streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    # If pr_id provided, ensure valid assignment
    if data.pr_id:
        # We can trust db.unassign_pr_from_streamer to check if assigned
        pass
    elif not streamer.get("assigned_pr_id"):
        # Legacy check if no pr_id provided (but now we support multi assign, so this check is weak)
        # Better to let DB handle it
        pass

    # Call DB with pr_id (if None, it unassigns ALL, but for manual unclaim we usually want specific)
    # However, if data.pr_id is None, we might be unclaiming ALL?
    # The new requirement says "pr_id=None for auto unassign".
    # For manual unclaim via API, we expect pr_id usually.

    results = await db.unassign_pr_from_streamer(
        data.streamer_id, pr_id=data.pr_id, end_reason=data.reason
    )

    if not results:
        # If we asked for specific pr_id and got nothing -> 404/400
        if data.pr_id:
            raise HTTPException(
                status_code=400, detail="Стример не закреплен за указанным сотрудником"
            )
        raise HTTPException(status_code=400, detail="Стример не закреплен")

    # For API response, we return the first one (backward compat) or list?
    # SpecUnclaimRequest implies single action usually.
    # Let's return the first one for the main response data structure.
    result = results[0]

    if broker:
        # Emit event for EACH unassigned PR
        for res in results:
            await broker.emit_spec_unclaimed(
                data.streamer_id,
                streamer["streamer_name"],
                res["pr_id"],
                res.get("duration_seconds", 0),
                data.reason,
                trace_id=trace_id,
            )

    return JSONResponse(
        content=success_envelope(
            data={
                "streamer_id": data.streamer_id,
                "streamer_name": streamer["streamer_name"],
                "pr_id": result["pr_id"],
                "duration_seconds": result.get("duration_seconds", 0),
                "unclaimed_count": len(results),
            },
            message=f"Unclaimed {streamer['streamer_name']}",
            code="SPEC_UNCLAIMED",
            trace_id=trace_id,
        )
    )





@router.get("/sessions/{pr_id}")
async def get_pr_sessions(
    request: Request,
    pr_id: int,
    db: "Database" = Depends(get_db),
    limit: int = 50,
):
    """Get recent spec sessions for a PR assistant."""
    trace_id = get_trace_id(request)
    sessions = await db.get_pr_spec_sessions(pr_id, limit)

    data = [SpecSessionResponse(**s).model_dump(mode="json") for s in sessions]

    return JSONResponse(
        content=success_envelope(
            data=data,
            message=f"Found {len(sessions)} sessions",
            trace_id=trace_id,
        )
    )


@router.get("/by-pr/{pr_id}")
async def get_current_streamer_for_pr(
    request: Request,
    pr_id: int,
    db: "Database" = Depends(get_db),
):
    """Get the session currently assigned to a PR assistant."""
    trace_id = get_trace_id(request)
    session = await db.get_pr_current_streamer(pr_id)

    if not session:
        return JSONResponse(
            content=success_envelope(
                data={"assigned": False, "streamer": None},
                message="No session assigned",
                trace_id=trace_id,
            )
        )

    if session.get("target_type") == "event":
        return JSONResponse(
            content=success_envelope(
                data={
                    "assigned": True,
                    "streamer": {
                        "event_id": session["event_id"],
                        "event_name": session["event_name"],
                        "assigned_at": str(session["assigned_at"]),
                    },
                },
                message=f"Assigned to event: {session['event_name']}",
                trace_id=trace_id,
            )
        )

    return JSONResponse(
        content=success_envelope(
            data={
                "assigned": True,
                "streamer": {
                    "streamer_id": session["streamer_id"],
                    "streamer_name": session["streamer_name"],
                    "assigned_at": str(session["assigned_at"]),
                },
            },
            message=f"Assigned to {session['streamer_name']}",
            trace_id=trace_id,
        )
    )


@router.get("/claimable")
async def get_claimable_streamers(
    request: Request,
    user_id: int,
    db: "Database" = Depends(get_db),
):
    """
    Get streamers available for claim by a specific user.

    Filters based on:
    - Online status
    - GTA category
    - User permissions (can_spec_probation for probation slots)

    Returns streamers with slot availability info.
    """
    trace_id = get_trace_id(request)

    # Get user capabilities via role-based permissions
    assistant = await db.get_assistant(user_id)
    can_spec_probation = False
    assigned_to_type = None
    assigned_to_name = None
    
    if assistant:
        role = assistant.get("role", "employee")
        permissions = await db.get_role_permissions(role)
        can_spec_probation = permissions.get("can_spec_probation", False)
        assigned_to_type = assistant.get("assigned_to_type")
        assigned_to_name = assistant.get("assigned_to_name")

    # Get all online GTA streamers with assignments
    all_streamers = await db.list_online_streamers()

    claimable = []
    gta_game_id = Config.gta5_game_id

    for s in all_streamers:
        # Must be GTA
        if str(s.get("game_id")) != gta_game_id:
            continue

        # Determine slot availability
        assignments = s.get("assignments")
        if not assignments:
            assignments = []
        elif isinstance(assignments, str):
            import json
            try:
                assignments = json.loads(assignments)
                if not assignments:
                    assignments = []
            except Exception:
                assignments = []

        main_free = True
        probation_free = True
        for a in assignments:
            if a is None:
                continue
            if a.get("is_probation"):
                probation_free = False
            else:
                main_free = False

        # Filter logic:
        # If streamer doesn't allow juniors, override probation_free to false
        if not s.get("allow_juniors", True):
            probation_free = False

        # - Regular user: only show if main_free
        # - Junior (can_spec_probation): show if main_free OR probation_free
        if can_spec_probation:
            if not main_free and not probation_free:
                continue  # Both slots taken
        else:
            if not main_free:
                continue  # Main slot taken

        claimable.append(
            {
                "streamer_id": s["streamer_id"],
                "streamer_name": s["streamer_name"],
                "priority": s.get("priority", 3),
                "is_pinned": s.get("is_pinned", False),
                "main_free": main_free,
                "probation_free": probation_free,
            }
        )

    # Get active events and add them if they have free slots
    active_events = await db.get_active_events()
    for e in active_events:
        slots = e.get("pr_slots", e.get("required_pr_count", 1))
        current = e.get("current_participants", 0)
        if current < slots:
            claimable.append(
                {
                    "is_event": True,
                    "event_id": e["id"],
                    "streamer_id": f"event_{e['id']}",  # Unique ID for the dropdown
                    "streamer_name": f"[Событие] {e['name']}",
                    "priority": e.get("priority", 0),
                    "is_pinned": e.get("is_pinned", False),
                    "main_free": True,  # Treat event slots as 'main' for UI simplicity
                    "probation_free": False, # Events don't have separate probation slots natively yet
                }
            )

    # Sort by priority (P0 first) and then by pinning
    claimable.sort(key=lambda x: (not x.get("is_pinned", False), x["priority"]))

    return JSONResponse(
        content=success_envelope(
            data={
                "streamers": claimable,
                "can_spec_probation": can_spec_probation,
                "assigned_to_type": assigned_to_type,
                "assigned_to_name": assigned_to_name,
            },
            message=f"Found {len(claimable)} claimable streamers",
            trace_id=trace_id,
        )
    )
