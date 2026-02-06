"""
Spec system routes for API.
Claim/unclaim/transfer streamers for PR assistants.
Refactored to use envelope responses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, List

if TYPE_CHECKING:
    from database import Database
    from services.broker import BrokerService

from config import Config
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import success_envelope
from schemas.spec import (
    ActiveSpecResponse,
    SpecClaimRequest,
    SpecSessionResponse,
    SpecSwapRequest,
    SpecTransferRequest,
    SpecUnclaimRequest,
)

router = APIRouter(prefix="/spec", tags=["Spec System"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


@router.get("/active")
async def get_active_specs(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """Get all currently active spec sessions."""
    trace_id = get_trace_id(request)
    active = await db.get_active_spec_sessions()

    data = [
        ActiveSpecResponse(
            streamer_id=a["streamer_id"],
            streamer_name=a["streamer_name"],
            pr_id=a["assigned_pr_id"],
            assigned_at=a["assigned_at"],
            duration_seconds=a["duration_seconds"] or 0,
        ).model_dump(mode="json")
        for a in active
    ]

    return JSONResponse(
        content=success_envelope(
            data=data,
            message=f"Found {len(active)} active specs",
            trace_id=trace_id,
        )
    )


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

    # Check if PR is already watching someone
    current = await db.get_pr_current_streamer(data.pr_id)
    if current:
        raise HTTPException(
            status_code=409,
            detail=f"Вы уже закреплены за стримером {current['streamer_name']}",
        )

    # Check slot availability using new assignments list
    assignments = streamer.get("assignments", [])
    requested_slot = "Probation" if data.is_probation else "Main"

    # Check if the requested slot is already taken
    for assignment in assignments:
        if assignment.get("is_probation") == data.is_probation:
            raise HTTPException(
                status_code=409,
                detail=f"Слот {requested_slot} уже занят PR <@{assignment['pr_id']}>",
            )

    # Claim with probation flag
    success = await db.assign_pr_to_streamer(
        data.streamer_id, data.pr_id, is_probation=data.is_probation
    )
    if not success:
        raise HTTPException(status_code=500, detail="Не удалось закрепить стримера")

    if broker:
        await broker.emit_spec_claimed(
            data.streamer_id,
            streamer["streamer_name"],
            data.pr_id,
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
             raise HTTPException(status_code=400, detail="Стример не закреплен за указанным сотрудником")
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
                "unclaimed_count": len(results)
            },
            message=f"Unclaimed {streamer['streamer_name']}",
            code="SPEC_UNCLAIMED",
            trace_id=trace_id,
        )
    )


@router.post("/transfer")
async def transfer_streamer(
    request: Request,
    data: SpecTransferRequest,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
):
    """Transfer a streamer from one PR to another."""
    trace_id = get_trace_id(request)

    streamer = await db.get_streamer(data.streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    # Check if target PR is free
    current = await db.get_pr_current_streamer(data.to_pr_id)
    if current:
        raise HTTPException(
            status_code=409,
            detail=f"Целевой PR уже закреплен за стримером {current['streamer_name']}",
        )

    # Unclaim from specific PR (Strict check: must be assigned to from_pr_id)
    results = await db.unassign_pr_from_streamer(
        data.streamer_id, pr_id=data.from_pr_id, end_reason="transfer"
    )
    
    if not results:
         raise HTTPException(
            status_code=400,
            detail="Стример не закреплен за указанным исходным PR",
        )
    
    result = results[0]

    # Claim for new PR
    # Warning: Transferring DOES NOT preserve is_probation status implicitly in this logic
    # It assumes standard claim. If we want to preserve, we should check `result['is_probation']`
    # Defaulting to regular claim for now as per original logic.
    await db.assign_pr_to_streamer(data.streamer_id, data.to_pr_id)

    if broker:
        await broker.publish(
            "spec.transferred",
            {
                "event": "spec.transferred",
                "streamer_id": data.streamer_id,
                "streamer_name": streamer["streamer_name"],
                "from_pr_id": data.from_pr_id,
                "to_pr_id": data.to_pr_id,
                "duration_seconds": result.get("duration_seconds", 0),
            },
        )

    return JSONResponse(
        content=success_envelope(
            data={
                "streamer_id": data.streamer_id,
                "streamer_name": streamer["streamer_name"],
                "from_pr_id": data.from_pr_id,
                "to_pr_id": data.to_pr_id,
            },
            message=f"Transferred {streamer['streamer_name']}",
            code="SPEC_TRANSFERRED",
            trace_id=trace_id,
        )
    )


@router.post("/swap")
async def swap_streamers(
    request: Request,
    data: SpecSwapRequest,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
):
    """Swap streamers between two PR assistants."""
    trace_id = get_trace_id(request)

    if data.pr1_id == data.pr2_id:
        raise HTTPException(status_code=400, detail="Нельзя обменяться с самим собой")

    try:
        result = await db.swap_pr_streamers(data.pr1_id, data.pr2_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if broker:
        await broker.publish(
            "spec.swapped",
            {
                "event": "spec.swapped",
                "pr1_id": data.pr1_id,
                "pr2_id": data.pr2_id,
                "pr1_new_streamer": result["pr1_new_streamer"]["streamer_name"],
                "pr2_new_streamer": result["pr2_new_streamer"]["streamer_name"],
            },
        )

    return JSONResponse(
        content=success_envelope(
            data={
                "pr1_id": data.pr1_id,
                "pr1_new_streamer": result["pr1_new_streamer"]["streamer_name"],
                "pr2_id": data.pr2_id,
                "pr2_new_streamer": result["pr2_new_streamer"]["streamer_name"],
            },
            message="Streamers swapped",
            code="SPEC_SWAPPED",
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
    """Get the streamer currently assigned to a PR assistant."""
    trace_id = get_trace_id(request)
    streamer = await db.get_pr_current_streamer(pr_id)

    if not streamer:
        return JSONResponse(
            content=success_envelope(
                data={"assigned": False, "streamer": None},
                message="No streamer assigned",
                trace_id=trace_id,
            )
        )

    return JSONResponse(
        content=success_envelope(
            data={
                "assigned": True,
                "streamer": {
                    "streamer_id": streamer["streamer_id"],
                    "streamer_name": streamer["streamer_name"],
                    "assigned_at": str(streamer["assigned_at"]),
                },
            },
            message=f"Assigned to {streamer['streamer_name']}",
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
    if assistant:
        role = assistant.get("role", "employee")
        permissions = await db.get_role_permissions(role)
        can_spec_probation = permissions.get("can_spec_probation", False)
    
    # Get all online GTA streamers with assignments
    all_streamers = await db.list_online_streamers()
    
    claimable = []
    gta_game_id = Config.gta5_game_id
    
    for s in all_streamers:
        # Must be GTA
        if str(s.get("game_id")) != gta_game_id:
            continue
        
        # Determine slot availability
        assignments = s.get("assignments", [])
        if isinstance(assignments, str):
            import json
            assignments = json.loads(assignments)
        
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
        # - Regular user: only show if main_free
        # - Junior (can_spec_probation): show if main_free OR probation_free
        if can_spec_probation:
            if not main_free and not probation_free:
                continue  # Both slots taken
        else:
            if not main_free:
                continue  # Main slot taken
        
        claimable.append({
            "streamer_id": s["streamer_id"],
            "streamer_name": s["streamer_name"],
            "priority": s.get("priority", 3),
            "main_free": main_free,
            "probation_free": probation_free,
        })
    
    # Sort by priority (P0 first)
    claimable.sort(key=lambda x: x["priority"])
    
    return JSONResponse(
        content=success_envelope(
            data={
                "streamers": claimable,
                "can_spec_probation": can_spec_probation,
            },
            message=f"Found {len(claimable)} claimable streamers",
            trace_id=trace_id,
        )
    )
