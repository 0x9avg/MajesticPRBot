from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db import Database

import math
from typing import Any, Dict, List, Optional

from dependencies import get_db, require_permission
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
    _principal: dict = Depends(require_permission("logs.admin.view")),
    db: "Database" = Depends(get_db),
):
    """
    Get admin logs with page-based pagination.
    Requires 'logs.admin.view' permission.
    """
    trace_id = get_trace_id(request)

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

    # Convert bigints to strings to prevent JS precision loss
    for log in logs:
        for field in ["id", "actor_id", "admin_id", "target_id"]:
            if log.get(field):
                log[field] = str(log[field])

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


@router.get("/assistant-actions/filters")
async def get_assistant_action_filters(
    request: Request,
    db: "Database" = Depends(get_db),
    _principal: dict = Depends(require_permission("logs.assistant_actions.view")),
):
    trace_id = get_trace_id(request)
    assistants = await db.list_assistant_identities()
    payload = [
        {
            "pr_id": str(item.get("pr_id")),
            "nickname": item.get("nickname"),
        }
        for item in assistants
        if item.get("pr_id") is not None
    ]
    return JSONResponse(
        content=success_envelope(
            data={"assistants": payload},
            message="Assistant action filters loaded",
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
    _principal: dict = Depends(require_permission("logs.assistant_actions.view")),
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
