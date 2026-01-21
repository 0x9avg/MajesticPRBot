"""
Assistants routes for API.
CRUD operations for PR assistants.
Refactored to use database methods.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status

from schemas.assistant import AssistantCreate, AssistantResponse, AssistantStatsResponse
from config import Config

router = APIRouter(prefix="/assistants", tags=["Assistants"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def format_spec_duration(seconds: int) -> str:
    """Format duration in seconds to human readable string."""
    if seconds < 60:
        return f"{seconds}с"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if hours > 0:
        return f"{hours}ч {minutes}м" if minutes > 0 else f"{hours}ч"
    return f"{minutes}м"


@router.get("", response_model=List[AssistantResponse])
async def list_assistants(db=Depends(get_db)):
    """Get all assistants."""
    assistants = await db.get_all_assistants()
    return [AssistantResponse(**a) for a in assistants]


@router.get("/top")
async def get_top_assistants(limit: int = 10, db=Depends(get_db)):
    """Get top assistants by spec time."""
    assistants = await db.get_top_assistants(limit)
    return assistants


@router.get("/{user_id}", response_model=AssistantResponse)
async def get_assistant(user_id: int, db=Depends(get_db)):
    """Get a specific assistant by Discord user ID."""
    assistant = await db.get_assistant(user_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")
    return AssistantResponse(**assistant)


@router.get("/{user_id}/stats", response_model=AssistantStatsResponse)
async def get_assistant_stats(user_id: int, db=Depends(get_db)):
    """Get detailed stats for an assistant."""
    stats = await db.get_assistant_stats(user_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    return AssistantStatsResponse(
        pr_id=stats["pr_id"],
        total_spec_seconds=stats["total_spec_seconds"],
        total_spec_formatted=format_spec_duration(stats["total_spec_seconds"]),
        session_count=stats["session_count"],
        daily_stats=[dict(d) for d in stats.get("daily_stats", [])],
    )


@router.post("", response_model=AssistantResponse, status_code=status.HTTP_201_CREATED)
async def create_assistant(data: AssistantCreate, db=Depends(get_db)):
    """Add a new assistant."""
    assistant = await db.create_assistant(data.user_id)
    if not assistant:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ассистент уже существует",
        )
    return AssistantResponse(**assistant)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assistant(user_id: int, db=Depends(get_db)):
    """Delete an assistant."""
    success = await db.delete_assistant(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Ассистент не найден")
    return None


@router.post("/{user_id}/reset")
async def reset_assistant_stats(user_id: int, db=Depends(get_db)):
    """Reset assistant statistics."""
    success = await db.reset_assistant_stats(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Ассистент не найден")
    return {"status": "reset", "user_id": user_id}



