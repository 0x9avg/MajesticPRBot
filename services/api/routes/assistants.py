"""API routes for PR staff (assistants) management."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database

from dependencies import get_current_user
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.assistant import (
    AssignmentUpdateResponse,
    AssistantAssignment,
    AssistantCreate,
    AssistantDeletedResponse,
    AssistantFull,
    AssistantPointsAdjustRequest,
    AssistantSavedResponse,
    AssistantSanctionsUpdateRequest,
    AssistantSessionRecord,
    AssistantSessionPatchRequest,
    AssistantWarningsUpdateRequest,
    DailyStatsResponse,
    DailyStatsUpdate,
    ManualSpecSession,
    SessionCreatedResponse,
    StatsResetResponse,
)
from schemas.envelope import success_envelope
from services.rbac import is_admin_role

router = APIRouter(prefix="/assistants", tags=["Assistants"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def ensure_admin_role(current_user: dict):
    """Allow only manager/developer for sensitive assistant operations."""
    if not is_admin_role(current_user.get("role")):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для доступа к админ-панели",
        )


@router.get("")
async def get_all_assistants(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """Get all PR staff members with their statistics."""
    trace_id = get_trace_id(request)
    assistants_data = await db.get_all_assistants()

    # Pre-process data for frontend (e.g. calculate hours)
    for assistant in assistants_data:
        assistant["total_spec_hours"] = round(assistant["total_spec_seconds"] / 3600, 2)

    # Convert to Pydantic models for serialization
    assistants = [AssistantFull.model_validate(a) for a in assistants_data]

    return JSONResponse(
        content=success_envelope(
            data=[a.model_dump(mode="json") for a in assistants],
            message=f"Found {len(assistants)} assistants",
            trace_id=trace_id,
        )
    )


@router.get("/{pr_id}")
async def get_assistant(
    request: Request,
    pr_id: int,
    db: "Database" = Depends(get_db),
):
    """Get a specific assistant by PR ID."""
    trace_id = get_trace_id(request)
    assistant_data = await db.get_assistant(pr_id)

    if not assistant_data:
        raise HTTPException(
            status_code=404, detail=f"Assistant with ID {pr_id} not found"
        )

    # Calculate hours
    assistant_data["total_spec_hours"] = round(
        assistant_data["total_spec_seconds"] / 3600, 2
    )

    assistant = AssistantFull.model_validate(assistant_data)

    return JSONResponse(
        content=success_envelope(
            data=assistant.model_dump(mode="json"),
            message="Assistant found",
            trace_id=trace_id,
        )
    )


@router.post("")
async def create_or_update_assistant(
    request: Request,
    assistant: AssistantCreate,
    db: "Database" = Depends(get_db),
):
    """Create or update a PR staff member."""
    trace_id = get_trace_id(request)

    # Validate role
    valid_roles = [
        "junior_employee",
        "employee",
        "senior_employee",
        "manager",
        "developer",
    ]
    if assistant.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}",
        )

    await db.create_or_update_assistant(
        pr_id=assistant.pr_id,
        nickname=assistant.nickname,
        role=assistant.role,
        experience_days=assistant.experience_days,
    )

    response_data = AssistantSavedResponse(
        pr_id=assistant.pr_id, nickname=assistant.nickname
    )

    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message=f"Assistant {assistant.nickname} saved successfully",
            code="ASSISTANT_SAVED",
            trace_id=trace_id,
        )
    )


@router.put("/{pr_id}/assign")
async def update_assignment(
    request: Request,
    pr_id: int,
    assignment: AssistantAssignment,
    db: "Database" = Depends(get_db),
):
    """Update assistant assignment to a streamer or event."""
    trace_id = get_trace_id(request)

    # Validate assignment type
    if assignment.assigned_to_type and assignment.assigned_to_type not in [
        "streamer",
        "event",
    ]:
        raise HTTPException(
            status_code=400,
            detail="Invalid assignment type. Must be 'streamer', 'event', or null",
        )

    # Check if assistant exists
    assistant = await db.get_assistant(pr_id)
    if not assistant:
        raise HTTPException(
            status_code=404, detail=f"Assistant with ID {pr_id} not found"
        )

    # Update assignment
    success = await db.update_assistant_assignment(
        pr_id=pr_id,
        assigned_to_type=assignment.assigned_to_type,
        assigned_to_id=assignment.assigned_to_id,
        assigned_to_name=assignment.assigned_to_name,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to update assignment")

    status_msg = (
        "freed"
        if not assignment.assigned_to_type
        else f"assigned to {assignment.assigned_to_name}"
    )

    response_data = AssignmentUpdateResponse(pr_id=pr_id, status=status_msg)

    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message=f"Assistant {assistant['nickname']} {status_msg}",
            code="ASSIGNMENT_UPDATED",
            trace_id=trace_id,
        )
    )


@router.delete("/{pr_id}")
async def delete_assistant(
    request: Request,
    pr_id: int,
    db: "Database" = Depends(get_db),
):
    """Delete an assistant."""
    trace_id = get_trace_id(request)
    success = await db.delete_assistant(pr_id)

    if not success:
        raise HTTPException(
            status_code=404, detail=f"Assistant with ID {pr_id} not found"
        )

    response_data = AssistantDeletedResponse(pr_id=pr_id)

    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message=f"Assistant {pr_id} deleted successfully",
            code="ASSISTANT_DELETED",
            trace_id=trace_id,
        )
    )


@router.get("/{pr_id}/logs")
async def get_assistant_logs(
    request: Request,
    pr_id: int,
    db: "Database" = Depends(get_db),
):
    """Get activity logs for a specific assistant."""
    trace_id = get_trace_id(request)
    logs = await db.get_assistant_logs(pr_id)

    return JSONResponse(
        content=success_envelope(
            data=logs,
            message=f"Found {len(logs)} log entries",
            trace_id=trace_id,
        )
    )


@router.get("/{pr_id}/sessions")
async def get_assistant_sessions(
    request: Request,
    pr_id: int,
    limit: int = 50,
    include_deleted: bool = False,
    user: dict = Depends(get_current_user),
    db: "Database" = Depends(get_db),
):
    """Get assistant sessions with admin-editable fields."""
    ensure_admin_role(user)
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    sessions = await db.get_assistant_sessions_detailed(
        pr_id=pr_id, limit=limit, include_deleted=include_deleted
    )
    response_data = [
        AssistantSessionRecord.model_validate(s).model_dump(mode="json")
        for s in sessions
    ]
    return JSONResponse(
        content=success_envelope(
            data=response_data,
            message=f"Found {len(response_data)} sessions",
            trace_id=trace_id,
        )
    )


@router.get("/{pr_id}/capabilities")
async def get_assistant_capabilities(
    request: Request,
    pr_id: int,
    db: "Database" = Depends(get_db),
):
    """Get assistant capabilities/permissions from role_permissions table (RBAC)."""
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)

    if not assistant:
        # Return default (no permissions) for unknown users
        default_perms = {
            "can_view_dashboard": False,
            "can_spec_probation": False,
            "can_manage_events": False,
            "can_manage_streamers": False,
            "can_execute_commands": False,
            "can_view_logs": False,
        }
        return JSONResponse(
            content=success_envelope(
                data=default_perms,
                message="Default permissions (unknown user)",
                trace_id=trace_id,
            )
        )

    role = assistant.get("role", "employee")
    permissions = await db.get_role_permissions(role)

    return JSONResponse(
        content=success_envelope(
            data=permissions,
            message=f"Permissions for role: {role}",
            trace_id=trace_id,
        )
    )


@router.post("/{pr_id}/reset")
async def reset_assistant_stats(
    request: Request,
    pr_id: int,
    user: dict = Depends(get_current_user),
    db: "Database" = Depends(get_db),
):
    """Reset all stats for an assistant (Manager/Admin feature)."""
    ensure_admin_role(user)
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)

    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    # Reset stats in assistants table
    await db.reset_assistant_stats(pr_id)

    response_data = StatsResetResponse(pr_id=pr_id, nickname=assistant.get("nickname"))

    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message=f"Stats for {assistant['nickname']} reset successfully",
            code="STATS_RESET",
            trace_id=trace_id,
        )
    )



@router.post("/{pr_id}/session")
async def create_manual_session(
    request: Request,
    pr_id: int,
    data: "ManualSpecSession",
    user: dict = Depends(get_current_user),
    db: "Database" = Depends(get_db),
):
    """Create a manual spec session (Admin feature for corrections)."""
    ensure_admin_role(user)
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)

    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    # Create completed session record
    created = await db.create_manual_spec_session(
        pr_id=pr_id,
        target_type=data.target_type,
        target_id=data.target_id,
        started_at=data.started_at,
        ended_at=data.ended_at,
        is_probation=data.is_probation,
        priority=data.priority,
        session_admin_comment=data.session_admin_comment,
    )
    if not created:
        raise HTTPException(status_code=500, detail="Не удалось создать ручную сессию")

    # Log admin action
    await db.log_admin_action_v2(
        actor_name=user.get("nickname", user.get("username", "unknown")),
        actor_role=user.get("role"),
        action="assistant.spec_time.add",
        target_type="assistant",
        target_id=str(pr_id),
        details={
            "summary": f"Manual spec session added for assistant {pr_id}",
            "payload": {
                "started_at": data.started_at.isoformat(),
                "ended_at": data.ended_at.isoformat(),
                "is_probation": data.is_probation,
                "target_name": data.target_name,
                "target_type": data.target_type,
                "target_id": str(data.target_id) if data.target_id is not None else None,
            },
            "meta": {
                "request_path": str(request.url.path),
                "method": request.method,
                "session_admin_comment": data.session_admin_comment,
                "actor_id": user.get("id"),
                "ip": request.client.host if request.client else None,
            },
        },
    )

    response_data = SessionCreatedResponse(
        pr_id=pr_id,
        started_at=data.started_at,
        ended_at=data.ended_at,
    )

    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message=f"Manual session created for {assistant['nickname']}",
            code="SESSION_CREATED",
            trace_id=trace_id,
        )
    )


@router.post("/{pr_id}/points/adjust")
async def adjust_assistant_points(
    request: Request,
    pr_id: int,
    data: AssistantPointsAdjustRequest,
    user: dict = Depends(get_current_user),
    db: "Database" = Depends(get_db),
):
    """Admin-only manual points adjustment (manual component only)."""
    ensure_admin_role(user)
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    result = await db.adjust_assistant_points(
        pr_id=pr_id,
        delta=data.delta,
        reason=data.reason,
        source=data.source or "manual_adjust",
    )
    if not result:
        raise HTTPException(status_code=500, detail="Не удалось скорректировать баллы")

    await db.log_admin_action_v2(
        actor_name=user.get("nickname", user.get("username", "unknown")),
        actor_role=user.get("role"),
        action="assistant.spec_points.adjust.permanent",
        target_type="assistant",
        target_id=str(pr_id),
        details={
            "summary": f"Adjusted manual points for assistant {pr_id}",
            "changes": {
                "before": result.get("before"),
                "after": result.get("after"),
                "delta": result.get("delta"),
                "reason": data.reason,
                "source": data.source or "manual_adjust",
            },
            "meta": {
                "trace_id": trace_id,
                "request_path": str(request.url.path),
                "method": request.method,
                "actor_id": user.get("id"),
                "ip": request.client.host if request.client else None,
            },
        },
    )

    return JSONResponse(
        content=success_envelope(
            data=result,
            message="Баллы ассистента скорректированы",
            code="ASSISTANT_POINTS_ADJUSTED",
            trace_id=trace_id,
        )
    )


@router.patch("/{pr_id}/sanctions")
async def patch_assistant_sanctions(
    request: Request,
    pr_id: int,
    data: AssistantSanctionsUpdateRequest,
    user: dict = Depends(get_current_user),
    db: "Database" = Depends(get_db),
):
    """Admin-only sanctions update."""
    ensure_admin_role(user)
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")
    if data.penalty_points is None and data.penalty_percent is None:
        raise HTTPException(status_code=400, detail="Нет полей для обновления санкций")

    result = await db.update_assistant_sanctions(
        pr_id=pr_id,
        penalty_points=data.penalty_points,
        penalty_percent=data.penalty_percent,
        reason=data.reason,
    )
    if not result:
        raise HTTPException(status_code=500, detail="Не удалось обновить санкции")

    await db.log_admin_action_v2(
        actor_name=user.get("nickname", user.get("username", "unknown")),
        actor_role=user.get("role"),
        action="assistant.sanctions.update",
        target_type="assistant",
        target_id=str(pr_id),
        details={
            "summary": f"Updated sanctions for assistant {pr_id}",
            "changes": {
                "before": result.get("before"),
                "after": result.get("after"),
                "reason": data.reason,
                "source": "sanction_update",
            },
            "meta": {
                "trace_id": trace_id,
                "request_path": str(request.url.path),
                "method": request.method,
                "actor_id": user.get("id"),
                "ip": request.client.host if request.client else None,
            },
        },
    )

    return JSONResponse(
        content=success_envelope(
            data=result,
            message="Санкции ассистента обновлены",
            code="ASSISTANT_SANCTIONS_UPDATED",
            trace_id=trace_id,
        )
    )


@router.post("/{pr_id}/warnings")
async def update_assistant_warnings(
    request: Request,
    pr_id: int,
    data: AssistantWarningsUpdateRequest,
    user: dict = Depends(get_current_user),
    db: "Database" = Depends(get_db),
):
    """Admin-only warnings update (oral/strict as units)."""
    ensure_admin_role(user)
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    result = await db.update_assistant_warnings(
        pr_id=pr_id,
        oral_delta=data.oral_delta,
        strict_delta=data.strict_delta,
        reason=data.reason,
    )
    if not result:
        raise HTTPException(
            status_code=400, detail="Изменение выговоров не применено"
        )

    await db.log_admin_action_v2(
        actor_name=user.get("nickname", user.get("username", "unknown")),
        actor_role=user.get("role"),
        action="assistant.warnings.update",
        target_type="assistant",
        target_id=str(pr_id),
        details={
            "summary": f"Updated warnings for assistant {pr_id}",
            "changes": {
                "before": result.get("before"),
                "after": result.get("after"),
                "delta": {
                    "oral_delta": data.oral_delta,
                    "strict_delta": data.strict_delta,
                    "units_delta": result.get("units_delta"),
                },
                "reason": data.reason,
                "source": "warning_update",
            },
            "meta": {
                "trace_id": trace_id,
                "request_path": str(request.url.path),
                "method": request.method,
                "actor_id": user.get("id"),
                "ip": request.client.host if request.client else None,
            },
        },
    )

    return JSONResponse(
        content=success_envelope(
            data=result,
            message="Выговоры ассистента обновлены",
            code="ASSISTANT_WARNINGS_UPDATED",
            trace_id=trace_id,
        )
    )


@router.patch("/{pr_id}/sessions/{session_id}")
async def patch_assistant_session(
    request: Request,
    pr_id: int,
    session_id: int,
    data: AssistantSessionPatchRequest,
    user: dict = Depends(get_current_user),
    db: "Database" = Depends(get_db),
):
    """Admin-only session patch with delta points recalculation."""
    ensure_admin_role(user)
    trace_id = get_trace_id(request)
    patch = data.model_dump(exclude_unset=True)
    reason = patch.pop("reason", None)
    if not patch:
        raise HTTPException(status_code=400, detail="Нет полей для обновления сессии")

    try:
        result = await db.update_assistant_session(
            pr_id=pr_id, session_id=session_id, patch=patch
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    await db.log_admin_action_v2(
        actor_name=user.get("nickname", user.get("username", "unknown")),
        actor_role=user.get("role"),
        action="assistant.spec_session.update",
        target_type="spec_session",
        target_id=str(session_id),
        details={
            "summary": f"Updated spec session {session_id} for assistant {pr_id}",
            "changes": {
                "before": result.get("before"),
                "after": result.get("after"),
                "reason": reason,
                "source": "session_edit",
            },
            "meta": {
                "trace_id": trace_id,
                "request_path": str(request.url.path),
                "method": request.method,
                "actor_id": user.get("id"),
                "session_id": session_id,
                "ip": request.client.host if request.client else None,
            },
        },
    )

    return JSONResponse(
        content=success_envelope(
            data=result,
            message="Сессия ассистента обновлена",
            code="ASSISTANT_SESSION_UPDATED",
            trace_id=trace_id,
        )
    )


@router.delete("/{pr_id}/sessions/{session_id}")
async def delete_assistant_session(
    request: Request,
    pr_id: int,
    session_id: int,
    reason: str = "admin_delete",
    user: dict = Depends(get_current_user),
    db: "Database" = Depends(get_db),
):
    """Admin-only soft delete of a spec session."""
    ensure_admin_role(user)
    trace_id = get_trace_id(request)
    result = await db.soft_delete_assistant_session(
        pr_id=pr_id,
        session_id=session_id,
        deleted_by_id=user.get("discord_id") or user.get("id"),
        reason=reason,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    await db.log_admin_action_v2(
        actor_name=user.get("nickname", user.get("username", "unknown")),
        actor_role=user.get("role"),
        action="assistant.spec_session.delete",
        target_type="spec_session",
        target_id=str(session_id),
        details={
            "summary": f"Soft deleted spec session {session_id} for assistant {pr_id}",
            "changes": {
                "before": result.get("before"),
                "after": result.get("after"),
                "reason": reason,
                "source": "session_soft_delete",
            },
            "meta": {
                "trace_id": trace_id,
                "request_path": str(request.url.path),
                "method": request.method,
                "actor_id": user.get("id"),
                "session_id": session_id,
                "ip": request.client.host if request.client else None,
            },
        },
    )

    return JSONResponse(
        content=success_envelope(
            data=result,
            message="Сессия ассистента удалена",
            code="ASSISTANT_SESSION_DELETED",
            trace_id=trace_id,
        )
    )
