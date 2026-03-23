"""API routes for statistics."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db import Database

from dependencies import require_permission
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import success_envelope

router = APIRouter(prefix="/stats", tags=["Stats"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


@router.get("/dashboard")
async def get_dashboard_stats(
    request: Request,
    db: "Database" = Depends(get_db),
    _principal: dict = Depends(require_permission("dashboard.view")),
):
    """Get aggregated statistics for the main dashboard."""
    trace_id = get_trace_id(request)
    stats = await db.get_dashboard_stats()

    return JSONResponse(
        content=success_envelope(
            data=stats,
            message="Dashboard stats retrieved",
            trace_id=trace_id,
        )
    )
