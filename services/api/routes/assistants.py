"""API routes for PR staff (assistants) management."""

from fastapi import APIRouter, HTTPException, Request, Depends
from typing import List, Optional
from pydantic import BaseModel
from schemas.assistant import (
    AssistantCreate,
    AssistantAssignment,
)

router = APIRouter(prefix="/assistants", tags=["Assistants"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


@router.get("")
async def get_all_assistants(db=Depends(get_db)):
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
async def get_assistant(pr_id: int, db=Depends(get_db)):
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
async def create_or_update_assistant(assistant: AssistantCreate, db=Depends(get_db)):
    """Create or update a PR staff member."""
    try:
        # Validate role
        valid_roles = ["junior_employee", "employee", "senior_employee", "manager", "developer"]
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
    pr_id: int, assignment: AssistantAssignment, db=Depends(get_db)
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
async def delete_assistant(pr_id: int, db=Depends(get_db)):
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
async def get_assistant_logs(pr_id: int, db=Depends(get_db)):
    """Get activity logs for a specific assistant."""
    try:
        logs = await db.get_assistant_logs(pr_id)
        return {"success": True, "data": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch logs: {str(e)}")


@router.get("/{pr_id}/capabilities")
async def get_assistant_capabilities(pr_id: int, db=Depends(get_db)):
    """Get assistant capabilities/permissions from role_permissions table (RBAC)."""
    try:
        assistant = await db.get_assistant(pr_id)
        
        if not assistant:
            # Return default (no permissions) for unknown users
            return {
                    "can_view_dashboard": False,
                    "can_spec_probation": False,
                    "can_manage_events": False,
                    "can_manage_streamers": False,
                    "can_execute_commands": False,
                    "can_view_logs": False,
                },
        
        role = assistant.get("role", "employee")
        permissions = await db.get_role_permissions(role)
        
        return permissions
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch capabilities: {str(e)}"
        )
