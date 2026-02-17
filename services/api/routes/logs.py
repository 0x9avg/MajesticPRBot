from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database

from typing import Any, Dict, List, Optional

from dependencies import get_current_user, get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Request

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get("/admin")
async def get_admin_logs(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
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
    Get admin logs.
    Requires 'can_view_admin_logs' permission.
    """
    permissions = user.get("permissions", {})
    if not permissions.get("can_view_admin_logs", False):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для просмотра логов администратора",
        )

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
    return logs
