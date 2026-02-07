"""API routes for PR staff (assistants) management."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, List, Optional

if TYPE_CHECKING:
    from database import Database

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.assistant import (
    AssistantAssignment,
    AssistantCreate,
    AssistantFull,
    DailyStatsUpdate,
    ManualSpecSession,
    AssistantSavedResponse,
    AssignmentUpdateResponse,
    AssistantDeletedResponse,
    StatsResetResponse,
    DailyStatsResponse,
    SessionCreatedResponse,
)
from schemas.envelope import success_envelope

router = APIRouter(prefix="/assistants", tags=["Assistants"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


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
        assistant["total_spec_hours"] = round(
            assistant["total_spec_seconds"] / 3600, 2
        )

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


# TODO: Add get logs logic
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
    db: "Database" = Depends(get_db),
):
    """Reset all stats for an assistant (Manager/Admin feature)."""
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)

    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    # Reset stats in assistants table
    await db.reset_assistant_stats(pr_id)

    response_data = StatsResetResponse(
        pr_id=pr_id, nickname=assistant.get("nickname")
    )

    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message=f"Stats for {assistant['nickname']} reset successfully",
            code="STATS_RESET",
            trace_id=trace_id,
        )
    )


@router.put("/{pr_id}/daily-stats")
async def update_daily_stats(
    request: Request,
    pr_id: int,
    data: "DailyStatsUpdate",
    db: "Database" = Depends(get_db),
):
    """Manually update daily stats for a specific date (Manager feature)."""
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)

    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    # Parse date string to date object
    try:
        date_obj = datetime.strptime(data.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    await db.update_daily_stats_manual(
        pr_id=pr_id,
        date_obj=date_obj,
        p0_seconds=data.p0_seconds or 0,
        p1_seconds=data.p1_seconds or 0,
        p2_seconds=data.p2_seconds or 0,
        p3_seconds=data.p3_seconds or 0,
        probation_seconds=data.probation_seconds or 0,
        total_points=data.total_points or 0.0,
    )

    response_data = DailyStatsResponse(pr_id=pr_id, date=data.date)

    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message=f"Daily stats for {assistant['nickname']} on {data.date} updated",
            code="DAILY_STATS_UPDATED",
            trace_id=trace_id,
        )
    )


@router.post("/{pr_id}/session")
async def create_manual_session(
    request: Request,
    pr_id: int,
    data: "ManualSpecSession",
    db: "Database" = Depends(get_db),
):
    """Create a manual spec session (Admin feature for corrections)."""
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)

    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    # Create completed session record
    await db.create_manual_spec_session(
        pr_id=pr_id,
        target_type=data.target_type,
        target_id=data.target_id,
        duration_seconds=data.duration_seconds,
        date_str=data.date,
        is_probation=data.is_probation,
        priority=data.priority,
    )

    # Log admin action
    await db.log_admin_action(
        admin_id=data.admin_id,
        action="create_manual_session",
        target_type="assistant",
        target_id=str(pr_id),
        details={
            "duration_seconds": data.duration_seconds,
            "date": data.date,
            "is_probation": data.is_probation,
            "target_name": data.target_name,
        },
    )

    response_data = SessionCreatedResponse(
        pr_id=pr_id, duration_seconds=data.duration_seconds
    )

    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message=f"Manual session created for {assistant['nickname']}",
            code="SESSION_CREATED",
            trace_id=trace_id,
        )
    )
