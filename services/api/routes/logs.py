from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database

import math
from typing import Any, Dict, List, Optional

from dependencies import get_current_user, get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import success_envelope

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get("/admin")
async def get_admin_logs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=500),
    action: Optional[List[str]] = Query(None),
    actor_name: Optional[str] = Query(None),
    admin_name: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    sort_by: str = Query(
        "created_at", pattern="^(created_at|admin_name|actor_name|action|target_name)$"
    ),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    user: Dict[str, Any] = Depends(get_current_user),
    db: "Database" = Depends(get_db),
):
    """
    Get admin logs with page-based pagination.
    Requires 'can_view_admin_logs' permission.
    """
    trace_id = get_trace_id(request)
    permissions = user.get("permissions", {})
    if not permissions.get("can_view_admin_logs", False):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для просмотра логов администратора",
        )

    offset = (page - 1) * limit

    filters = {
        "action": action,
        "actor_name": actor_name or admin_name,
        "admin_name": admin_name,
        "target_type": target_type,
        "kind": kind,
        "start_date": start_date,
        "end_date": end_date,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}

    logs = await db.get_admin_logs(
        limit=limit,
        offset=offset,
        filters=filters,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    total = await db.count_admin_logs(filters=filters)
    pages = math.ceil(total / limit) if total > 0 else 1

    return JSONResponse(
        content=success_envelope(
            data={
                "items": logs,
                "total": total,
                "page": page,
                "pages": pages,
            },
            message=f"Found {total} admin log entries",
            trace_id=trace_id,
        )
    )


@router.get("/pr-actions")
async def get_pr_action_logs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    pr_id: Optional[str] = Query(None),
    priority: Optional[int] = Query(None, ge=0, le=3),
    target_type: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None, pattern="^(join|leave)$"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: "Database" = Depends(get_db),
):
    """
    Get PR action logs (claims/unclaims) with pagination and filtering.

    Returns a chronological feed of assistant join/leave events
    for streamers and events.
    """
    trace_id = get_trace_id(request)
    offset = (page - 1) * limit

    filters = {
        "pr_id": pr_id,
        "priority": priority,
        "target_type": target_type,
        "action_type": action_type,
        "date_from": date_from,
        "date_to": date_to,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}

    result = await db.get_pr_action_logs(
        limit=limit,
        offset=offset,
        filters=filters,
    )

    total = result.get("total", 0)
    pages = math.ceil(total / limit) if total > 0 else 1

    return JSONResponse(
        content=success_envelope(
            data={
                "items": result.get("items", []),
                "total": total,
                "page": page,
                "pages": pages,
            },
            message=f"Found {total} PR action log entries",
            trace_id=trace_id,
        )
    )

