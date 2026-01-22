"""API routes for statistics."""

from fastapi import APIRouter, HTTPException, Request, Depends

router = APIRouter(prefix="/stats", tags=["Stats"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


@router.get("/dashboard")
async def get_dashboard_stats(db=Depends(get_db)):
    """Get aggregated statistics for the main dashboard."""
    try:
        stats = await db.get_dashboard_stats()
        return {
            "success": True,
            "data": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch dashboard stats: {str(e)}")
