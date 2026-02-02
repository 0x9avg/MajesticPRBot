"""API routes for PR staff (assistants) management."""

from __future__ import annotations
from typing import TYPE_CHECKING, Annotated, List, Optional

if TYPE_CHECKING:
    from database import Database

from fastapi import APIRouter, Depends, HTTPException, Request
from schemas.assistant import (
    AssistantAssignment,
    AssistantCreate,
    DailyStatsUpdate,
    ManualSpecSession,
)

router = APIRouter(prefix="/assistants", tags=["Assistants"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


@router.get("")
async def get_all_assistants(db: Annotated["Database", Depends(get_db)]):
    """Get all PR staff members with their statistics."""
    try:
        assistants = await db.get_all_assistants()

        # Convert total_spec_seconds to hours for frontend
        for assistant in assistants:
            assistant["total_spec_hours"] = round(
                assistant["total_spec_seconds"] / 3600, 2
            )

        return {"success": True, "data": assistants, "count": len(assistants)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch assistants: {str(e)}"
        )


@router.get("/{pr_id}")
async def get_assistant(pr_id: int, db: Annotated["Database", Depends(get_db)]):
    """Get a specific assistant by PR ID."""
    try:
        assistant = await db.get_assistant(pr_id)

        if not assistant:
            raise HTTPException(
                status_code=404, detail=f"Assistant with ID {pr_id} not found"
            )

        # Convert total_spec_seconds to hours
        assistant["total_spec_hours"] = round(assistant["total_spec_seconds"] / 3600, 2)

        return {"success": True, "data": assistant}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch assistant: {str(e)}"
        )


@router.post("")
async def create_or_update_assistant(assistant: AssistantCreate, db: Annotated["Database", Depends(get_db)]):
    """Create or update a PR staff member."""
    try:
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

        return {
            "success": True,
            "message": f"Assistant {assistant.nickname} saved successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to save assistant: {str(e)}"
        )


@router.put("/{pr_id}/assign")
async def update_assignment(
    pr_id: int, assignment: AssistantAssignment, db: Annotated["Database", Depends(get_db)]
):
    """Update assistant assignment to a streamer or event."""
    try:
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

        return {
            "success": True,
            "message": f"Assistant {assistant['nickname']} {status_msg}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update assignment: {str(e)}"
        )


@router.delete("/{pr_id}")
async def delete_assistant(pr_id: int, db: Annotated["Database", Depends(get_db)]):
    """Delete an assistant."""
    try:
        success = await db.delete_assistant(pr_id)

        if not success:
            raise HTTPException(
                status_code=404, detail=f"Assistant with ID {pr_id} not found"
            )

        return {"success": True, "message": f"Assistant {pr_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete assistant: {str(e)}"
        )


@router.get("/{pr_id}/logs")
async def get_assistant_logs(pr_id: int, db: Annotated["Database", Depends(get_db)]):
    """Get activity logs for a specific assistant."""
    try:
        logs = await db.get_assistant_logs(pr_id)
        return {"success": True, "data": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch logs: {str(e)}")


@router.get("/{pr_id}/capabilities")
async def get_assistant_capabilities(pr_id: int, db: Annotated["Database", Depends(get_db)]):
    """Get assistant capabilities/permissions from role_permissions table (RBAC)."""
    try:
        assistant = await db.get_assistant(pr_id)

        if not assistant:
            # Return default (no permissions) for unknown users
            return (
                {
                    "can_view_dashboard": False,
                    "can_spec_probation": False,
                    "can_manage_events": False,
                    "can_manage_streamers": False,
                    "can_execute_commands": False,
                    "can_view_logs": False,
                },
            )

        role = assistant.get("role", "employee")
        permissions = await db.get_role_permissions(role)

        return permissions
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch capabilities: {str(e)}"
        )


@router.post("/{pr_id}/reset")
async def reset_assistant_stats(pr_id: int, db: Annotated["Database", Depends(get_db)]):
    """Reset all stats for an assistant (Manager/Admin feature)."""
    try:
        assistant = await db.get_assistant(pr_id)
        if not assistant:
            raise HTTPException(status_code=404, detail="Ассистент не найден")

        # Reset stats in assistants table
        await db.reset_assistant_stats(pr_id)

        return {
            "success": True,
            "message": f"Stats for {assistant['nickname']} reset successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to reset stats: {str(e)}"
        )


@router.put("/{pr_id}/daily-stats")
async def update_daily_stats(
    pr_id: int,
    data: "DailyStatsUpdate",
    db: Annotated["Database", Depends(get_db)],
):
    """Manually update daily stats for a specific date (Manager feature)."""
    from datetime import datetime
    
    try:
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

        return {
            "success": True,
            "message": f"Daily stats for {assistant['nickname']} on {data.date} updated",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update daily stats: {str(e)}"
        )


@router.post("/{pr_id}/session")
async def create_manual_session(
    pr_id: int,
    data: "ManualSpecSession",
    db: Annotated["Database", Depends(get_db)],
):
    """Create a manual spec session (Admin feature for corrections)."""
    from datetime import datetime
    
    try:
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

        return {
            "success": True,
            "message": f"Manual session created for {assistant['nickname']}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create manual session: {str(e)}"
        )
