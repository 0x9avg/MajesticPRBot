"""API routes for statistics."""

from __future__ import annotations
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from database import Database

from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter(prefix="/stats", tags=["Stats"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


@router.get("/dashboard")
async def get_dashboard_stats(db: Annotated["Database", Depends(get_db)]):
    """Get aggregated statistics for the main dashboard."""
    try:
        stats = await db.get_dashboard_stats()
        return {"success": True, "data": stats}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch dashboard stats: {str(e)}"
        )
