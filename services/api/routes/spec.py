"""
Spec system routes for API.
Claim/unclaim/transfer streamers for PR assistants.
Refactored to use database methods.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request

from schemas.spec import (
    SpecClaimRequest,
    SpecUnclaimRequest,
    SpecTransferRequest,
    SpecSwapRequest,
    SpecSessionResponse,
    ActiveSpecResponse,
)
from config import Config

router = APIRouter(prefix="/spec", tags=["Spec System"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


@router.get("/active", response_model=List[ActiveSpecResponse])
async def get_active_specs(db=Depends(get_db)):
    """Get all currently active spec sessions."""
    active = await db.get_active_spec_sessions()

    return [
        ActiveSpecResponse(
            streamer_id=a["streamer_id"],
            streamer_name=a["streamer_name"],
            pr_id=a["assigned_pr_id"],
            assigned_at=a["assigned_at"],
            duration_seconds=a["duration_seconds"] or 0,
        )
        for a in active
    ]


@router.post("/claim")
async def claim_streamer(
    data: SpecClaimRequest,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """Claim a streamer for a PR assistant (supports Probation Slot Logic)."""
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
        )

    return {
        "status": "claimed",
        "streamer_id": data.streamer_id,
        "streamer_name": streamer["streamer_name"],
        "pr_id": data.pr_id,
        "is_probation": data.is_probation,
    }


@router.post("/unclaim")
async def unclaim_streamer(
    data: SpecUnclaimRequest,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """Unclaim a streamer."""
    streamer = await db.get_streamer(data.streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    if not streamer.get("assigned_pr_id"):
        raise HTTPException(status_code=400, detail="Стример не закреплен")

    pr_id = streamer["assigned_pr_id"]

    result = await db.unassign_pr_from_streamer(data.streamer_id, data.reason)

    if not result:
        raise HTTPException(status_code=500, detail="Не удалось открепить стримера")

    if broker:
        await broker.emit_spec_unclaimed(
            data.streamer_id,
            streamer["streamer_name"],
            pr_id,
            result.get("duration_seconds", 0),
            data.reason,
        )

    return {
        "status": "unclaimed",
        "streamer_id": data.streamer_id,
        "streamer_name": streamer["streamer_name"],
        "pr_id": pr_id,
        "duration_seconds": result.get("duration_seconds", 0),
    }


@router.post("/transfer")
async def transfer_streamer(
    data: SpecTransferRequest,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """Transfer a streamer from one PR to another."""
    streamer = await db.get_streamer(data.streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    if streamer.get("assigned_pr_id") != data.from_pr_id:
        raise HTTPException(
            status_code=400,
            detail="Стример не закреплен за указанным PR",
        )

    # Check if target PR is free
    current = await db.get_pr_current_streamer(data.to_pr_id)
    if current:
        raise HTTPException(
            status_code=409,
            detail=f"Целевой PR уже закреплен за стримером {current['streamer_name']}",
        )

    # Unclaim from current
    result = await db.unassign_pr_from_streamer(data.streamer_id, "transfer")

    # Claim for new PR
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
                "duration_seconds": result.get("duration_seconds", 0) if result else 0,
            },
        )

    return {
        "status": "transferred",
        "streamer_id": data.streamer_id,
        "streamer_name": streamer["streamer_name"],
        "from_pr_id": data.from_pr_id,
        "to_pr_id": data.to_pr_id,
    }


@router.post("/swap")
async def swap_streamers(
    data: SpecSwapRequest,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """Swap streamers between two PR assistants."""
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
    
    return {
        "status": "swapped",
        "pr1_id": data.pr1_id,
        "pr1_new_streamer": result["pr1_new_streamer"]["streamer_name"],
        "pr2_id": data.pr2_id,
        "pr2_new_streamer": result["pr2_new_streamer"]["streamer_name"],
    }


@router.get("/sessions/{pr_id}", response_model=List[SpecSessionResponse])
async def get_pr_sessions(pr_id: int, limit: int = 50, db=Depends(get_db)):
    """Get recent spec sessions for a PR assistant."""
    sessions = await db.get_pr_spec_sessions(pr_id, limit)
    return [SpecSessionResponse(**s) for s in sessions]


@router.get("/by-pr/{pr_id}")
async def get_current_streamer_for_pr(pr_id: int, db=Depends(get_db)):
    """Get the streamer currently assigned to a PR assistant."""
    streamer = await db.get_pr_current_streamer(pr_id)

    if not streamer:
        return {"assigned": False, "streamer": None}

    return {
        "assigned": True,
        "streamer": {
            "streamer_id": streamer["streamer_id"],
            "streamer_name": streamer["streamer_name"],
            "assigned_at": streamer["assigned_at"],
        },
    }
