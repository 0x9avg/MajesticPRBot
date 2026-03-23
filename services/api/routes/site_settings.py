"""Admin RBAC and site maintenance routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from dependencies import require_any_permission, require_permission
from middleware import get_trace_id
from schemas.envelope import success_envelope
from schemas.site_settings import (
    RbacSnapshot,
    SiteMaintenanceSnapshot,
    SiteMaintenanceUpdateRequest,
    SiteRolePermissionsUpdateRequest,
)
from services.rbac import (
    STAFF_ROLES,
    get_manageable_roles,
    get_permission_catalog,
    get_permission_implications,
)

if TYPE_CHECKING:
    from db import Database


rbac_router = APIRouter(prefix="/admin/rbac", tags=["RBAC"])
site_maintenance_router = APIRouter(
    prefix="/admin/site-maintenance",
    tags=["Site Maintenance"],
)
router = APIRouter()


def get_db(request: Request):
    return request.app.state.database


def _build_role_permissions_matrix(snapshot: dict[str, Any]) -> dict[str, dict[str, bool]]:
    rows = snapshot.get("role_permissions") or []
    matrix = {
        role: {permission: False for permission in get_permission_catalog()}
        for role in STAFF_ROLES
    }
    for row in rows:
        role = str(row.get("role") or "").strip()
        if role not in matrix:
            continue
        permissions = row.get("permissions") or {}
        matrix[role] = {
            permission: bool(permissions.get(permission, False))
            for permission in get_permission_catalog()
        }
    return matrix


def _build_rbac_payload(
    snapshot: dict[str, Any],
    *,
    actor_role: str | None,
) -> dict[str, Any]:
    full_matrix = _build_role_permissions_matrix(snapshot)
    visible_roles = list(get_manageable_roles(actor_role))
    payload = RbacSnapshot(
        roles=visible_roles,
        permissions=list(get_permission_catalog()),
        matrix={role: full_matrix[role] for role in visible_roles},
        permission_implications=get_permission_implications(),
    )
    return payload.model_dump(mode="json")


@rbac_router.get("")
async def get_rbac_snapshot(
    request: Request,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_any_permission("rbac.view", "rbac.update")),
):
    trace_id = get_trace_id(request)
    snapshot = await db.get_site_settings_snapshot()
    return JSONResponse(
        content=success_envelope(
            data=_build_rbac_payload(snapshot, actor_role=principal.get("role")),
            message="RBAC snapshot retrieved",
            trace_id=trace_id,
        )
    )


@rbac_router.put("")
async def replace_role_permissions(
    request: Request,
    data: SiteRolePermissionsUpdateRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("rbac.update")),
):
    trace_id = get_trace_id(request)
    requested_roles = set(data.matrix.keys())
    known_roles = set(STAFF_ROLES)
    unknown_roles = sorted(requested_roles - known_roles)
    if unknown_roles:
        raise HTTPException(
            status_code=400,
            detail="Неизвестные роли: " + ", ".join(unknown_roles),
        )

    allowed_roles = set(get_manageable_roles(principal.get("role")))
    forbidden_roles = sorted(requested_roles - allowed_roles)
    if forbidden_roles:
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для изменения ролей: " + ", ".join(forbidden_roles),
        )

    snapshot = await db.get_site_settings_snapshot()
    current_matrix = _build_role_permissions_matrix(snapshot)
    for role in allowed_roles:
        if role not in data.matrix:
            continue
        current_matrix[role] = {
            **current_matrix[role],
            **{
                permission: bool(flag)
                for permission, flag in data.matrix[role].items()
            },
        }

    items = [
        {
            "role": role,
            "permissions": current_matrix[role],
        }
        for role in STAFF_ROLES
    ]

    try:
        await db.replace_role_permissions_snapshot(items)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    await db.log_admin_action_v2(
        actor_name=principal.get("nickname") or principal.get("service_name") or "Unknown",
        actor_role=principal.get("role"),
        action="rbac.matrix.update",
        target_type="rbac",
        target_id="matrix",
        details={
            "summary": "Updated RBAC matrix",
            "payload": {"roles": sorted(data.matrix.keys())},
            "meta": {
                "request_path": str(request.url.path),
                "method": request.method,
                "actor_id": principal.get("id") or principal.get("discord_id"),
            },
        },
    )

    snapshot = await db.get_site_settings_snapshot()
    return JSONResponse(
        content=success_envelope(
            data=_build_rbac_payload(snapshot, actor_role=principal.get("role")),
            message="RBAC matrix updated",
            code="RBAC_UPDATED",
            trace_id=trace_id,
        )
    )


@site_maintenance_router.get("")
async def get_site_maintenance(
    request: Request,
    db: "Database" = Depends(get_db),
    _principal: dict = Depends(
        require_any_permission("site.maintenance.view", "site.maintenance.update")
    ),
):
    trace_id = get_trace_id(request)
    payload = SiteMaintenanceSnapshot(
        enabled=await db.is_site_maintenance_enabled()
    )
    return JSONResponse(
        content=success_envelope(
            data=payload.model_dump(mode="json"),
            message="Site maintenance state retrieved",
            trace_id=trace_id,
        )
    )


@site_maintenance_router.patch("")
async def update_site_maintenance(
    request: Request,
    data: SiteMaintenanceUpdateRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("site.maintenance.update")),
):
    trace_id = get_trace_id(request)
    enabled = await db.set_site_maintenance_enabled(data.enabled)

    await db.log_admin_action_v2(
        actor_name=principal.get("nickname") or principal.get("service_name") or "Unknown",
        actor_role=principal.get("role"),
        action="site.maintenance.update",
        target_type="site_maintenance",
        target_id="global",
        details={
            "summary": "Updated site maintenance mode",
            "payload": {"enabled": enabled},
            "meta": {
                "request_path": str(request.url.path),
                "method": request.method,
                "actor_id": principal.get("id") or principal.get("discord_id"),
            },
        },
    )

    payload = SiteMaintenanceSnapshot(enabled=enabled)
    return JSONResponse(
        content=success_envelope(
            data=payload.model_dump(mode="json"),
            message="Maintenance mode updated",
            code="SITE_MAINTENANCE_UPDATED",
            trace_id=trace_id,
        )
    )


router.include_router(rbac_router)
router.include_router(site_maintenance_router)
