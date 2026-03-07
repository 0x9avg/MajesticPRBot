"""
Spec system routes for API.
Claim/unclaim/transfer streamers for PR assistants.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database
    from services.broker import BrokerService

from config import Config
from dependencies import get_current_principal, require_permission
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import success_envelope
from schemas.spec import SpecClaimRequest, SpecSessionResponse, SpecUnclaimRequest

router = APIRouter(prefix="/spec", tags=["Spec System"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


def _has_permission(principal: dict, permission: str) -> bool:
    permissions = principal.get("permissions") or {}
    return bool(permissions.get(permission, False))


def _require_permission_local(principal: dict, permission: str) -> None:
    if not _has_permission(principal, permission):
        raise HTTPException(
            status_code=403,
            detail=f"Недостаточно прав: требуется '{permission}'",
        )


def _resolve_user_pr_id(principal: dict) -> int:
    discord_id = principal.get("discord_id")
    if discord_id is None:
        raise HTTPException(status_code=400, detail="User has no discord_id")
    try:
        return int(discord_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid discord_id")


async def _build_claimable_response(
    request: Request,
    db: "Database",
    user_id: int,
) -> JSONResponse:
    """Build claimable targets payload for a specific user ID."""
    trace_id = get_trace_id(request)

    assistant = await db.get_assistant(user_id)
    can_spec_probation = False
    assigned_to_type = None
    assigned_to_name = None

    if assistant:
        role = assistant.get("role", "employee")
        permissions = await db.get_role_permissions(role)
        can_spec_probation = bool(permissions.get("spec.claim.probation", False))
        assigned_to_type = assistant.get("assigned_to_type")
        assigned_to_name = assistant.get("assigned_to_name")

    all_streamers = await db.list_online_streamers()
    claimable: list[dict] = []
    gta_game_id = Config.gta5_game_id

    for streamer in all_streamers:
        if str(streamer.get("game_id")) != gta_game_id:
            continue

        assignments = streamer.get("assignments")
        if not assignments:
            assignments = []
        elif isinstance(assignments, str):
            import json

            try:
                assignments = json.loads(assignments) or []
            except Exception:
                assignments = []

        main_free = True
        probation_free = True
        for assignment in assignments:
            if assignment is None:
                continue
            if assignment.get("is_probation"):
                probation_free = False
            else:
                main_free = False

        if not streamer.get("allow_juniors", True):
            probation_free = False

        if can_spec_probation:
            if not main_free and not probation_free:
                continue
        else:
            if not main_free:
                continue

        claimable.append(
            {
                "streamer_id": streamer["streamer_id"],
                "streamer_name": streamer["streamer_name"],
                "priority": streamer.get("priority", 3),
                "is_pinned": streamer.get("is_pinned", False),
                "main_free": main_free,
                "probation_free": probation_free,
            }
        )

    active_events = await db.get_active_events()
    for event in active_events:
        slots = event.get("pr_slots", event.get("required_pr_count", 1))
        current = event.get("current_participants", 0)
        if current < slots:
            claimable.append(
                {
                    "is_event": True,
                    "event_id": event["id"],
                    "streamer_id": f"event_{event['id']}",
                    "streamer_name": f"[Событие] {event['name']}",
                    "priority": event.get("priority", 0),
                    "is_pinned": event.get("is_pinned", False),
                    "main_free": True,
                    "probation_free": False,
                }
            )

    claimable.sort(key=lambda item: (not item.get("is_pinned", False), item["priority"]))

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


async def _claim_for_pr(
    *,
    request: Request,
    data: SpecClaimRequest,
    pr_id: int,
    db: "Database",
    broker: "BrokerService",
) -> JSONResponse:
    trace_id = get_trace_id(request)

    streamer = await db.get_streamer(data.streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")
    if not streamer.get("is_online"):
        raise HTTPException(status_code=400, detail="Стример в оффлайне")
    if str(streamer.get("game_id")) != Config.gta5_game_id:
        raise HTTPException(status_code=400, detail="Стример не в категории GTA 5")
    if data.is_probation and not streamer.get("allow_juniors", True):
        raise HTTPException(
            status_code=403,
            detail="Стажерам запрещено закрепляться за этим стримером",
        )

    current = await db.get_pr_current_streamer(pr_id)
    if current:
        target_name = current.get("streamer_name") or current.get("event_name") or "целью"
        raise HTTPException(status_code=409, detail=f"Пользователь уже закреплен за {target_name}")

    active_event = await db.get_user_active_event_participation(pr_id)
    if active_event:
        raise HTTPException(
            status_code=409,
            detail=f"У пользователя уже есть активный спек на событие «{active_event['name']}»",
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
        await db.assign_pr_to_streamer(data.streamer_id, pr_id, is_probation=data.is_probation)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))

    if broker:
        await broker.emit_spec_claimed(
            data.streamer_id,
            streamer["streamer_name"],
            pr_id,
            data={"is_probation": data.is_probation},
            trace_id=trace_id,
        )

    return JSONResponse(
        content=success_envelope(
            data={
                "streamer_id": data.streamer_id,
                "streamer_name": streamer["streamer_name"],
                "pr_id": pr_id,
                "is_probation": data.is_probation,
            },
            message=f"Claimed {streamer['streamer_name']}",
            code="SPEC_CLAIMED",
            trace_id=trace_id,
        )
    )


@router.post("/claim")
async def claim_streamer(
    request: Request,
    data: SpecClaimRequest,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    principal: dict = Depends(get_current_principal),
):
    """Claim a streamer for the authenticated user."""
    if principal.get("principal_type") == "service":
        raise HTTPException(
            status_code=403,
            detail="Service principal must use /api/spec/claim/{pr_id}",
        )

    _require_permission_local(principal, "spec.claim.main")
    if data.is_probation:
        _require_permission_local(principal, "spec.claim.probation")

    pr_id = _resolve_user_pr_id(principal)
    return await _claim_for_pr(
        request=request,
        data=data,
        pr_id=pr_id,
        db=db,
        broker=broker,
    )


@router.post("/claim/{pr_id}")
async def claim_streamer_for_pr(
    request: Request,
    pr_id: int,
    data: SpecClaimRequest,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    principal: dict = Depends(get_current_principal),
):
    """Service/admin claim flow for a target PR ID."""
    _require_permission_local(principal, "spec.claim.main")
    if data.is_probation:
        _require_permission_local(principal, "spec.claim.probation")
    if principal.get("principal_type") != "service" and not _has_permission(principal, "spec.unclaim.any"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для назначения другим пользователям")

    return await _claim_for_pr(
        request=request,
        data=data,
        pr_id=pr_id,
        db=db,
        broker=broker,
    )


@router.post("/unclaim")
async def unclaim_streamer(
    request: Request,
    data: SpecUnclaimRequest,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    principal: dict = Depends(get_current_principal),
):
    """Unclaim own streamer assignment for user, or all assignments for service."""
    trace_id = get_trace_id(request)
    principal_type = principal.get("principal_type")
    if principal_type == "user":
        _require_permission_local(principal, "spec.unclaim.self")
        target_pr_id: int | None = _resolve_user_pr_id(principal)
    else:
        _require_permission_local(principal, "spec.unclaim.any")
        target_pr_id = None

    streamer = await db.get_streamer(data.streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    results = await db.unassign_pr_from_streamer(
        data.streamer_id,
        pr_id=target_pr_id,
        end_reason=data.reason,
    )
    if not results:
        raise HTTPException(status_code=400, detail="Стример не закреплен")

    result = results[0]
    if broker:
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


@router.post("/unclaim/{pr_id}")
async def unclaim_streamer_for_pr(
    request: Request,
    pr_id: int,
    data: SpecUnclaimRequest,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    principal: dict = Depends(require_permission("spec.unclaim.any")),
):
    """Admin/service unclaim flow for target PR."""
    trace_id = get_trace_id(request)

    streamer = await db.get_streamer(data.streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    results = await db.unassign_pr_from_streamer(
        data.streamer_id,
        pr_id=pr_id,
        end_reason=data.reason,
    )
    if not results:
        raise HTTPException(
            status_code=400,
            detail="Стример не закреплен за указанным сотрудником",
        )

    result = results[0]
    if broker:
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
    principal: dict = Depends(require_permission("spec.view_self_sessions")),
):
    """Get recent spec sessions for a PR assistant."""
    if principal.get("principal_type") == "user":
        own_id = _resolve_user_pr_id(principal)
        if own_id != pr_id and not _has_permission(principal, "spec.unclaim.any"):
            raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра чужих сессий")

    trace_id = get_trace_id(request)
    sessions = await db.get_pr_spec_sessions(pr_id, limit)
    data = [SpecSessionResponse(**session).model_dump(mode="json") for session in sessions]

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
    principal: dict = Depends(require_permission("spec.view_self_sessions")),
):
    """Get the session currently assigned to a PR assistant."""
    if principal.get("principal_type") == "user":
        own_id = _resolve_user_pr_id(principal)
        if own_id != pr_id and not _has_permission(principal, "spec.unclaim.any"):
            raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра чужого закрепления")

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
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("spec.view_claimable")),
):
    """Get claimable streamers for authenticated user."""
    if principal.get("principal_type") == "service":
        raise HTTPException(status_code=403, detail="Service principal must use /api/spec/claimable/{pr_id}")
    user_id = _resolve_user_pr_id(principal)
    return await _build_claimable_response(request=request, db=db, user_id=user_id)


@router.get("/claimable/{pr_id}")
async def get_claimable_streamers_for_pr(
    request: Request,
    pr_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("spec.view_claimable")),
):
    """Service/admin claimable list for a target PR."""
    if principal.get("principal_type") != "service" and not _has_permission(principal, "spec.unclaim.any"):
        raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра claimable у других пользователей")
    return await _build_claimable_response(request=request, db=db, user_id=pr_id)
