"""Routes for punishment removals workflow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from db import Database

from dependencies import get_current_principal, require_permission
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import conflict_envelope, not_found_envelope, success_envelope
from schemas.enums import PunishmentRemovalType, WorkflowStatus
from schemas.removals import (
    PunishmentRemovalCreate,
    PunishmentRemovalHistoryResponse,
    PunishmentRemovalRecord,
    PunishmentRemovalUpdate,
)

router = APIRouter(prefix="/removals", tags=["Removals"])

MSK = timezone(timedelta(hours=3))


def get_db(request: Request):
    return request.app.state.database


def _has_permission(principal: dict, permission: str) -> bool:
    permissions = principal.get("permissions") or {}
    return bool(permissions.get(permission, False))


def _current_actor_id(principal: dict) -> int:
    raw = principal.get("discord_id")
    if raw is None:
        raw = principal.get("id")
    if raw is None:
        raise HTTPException(status_code=400, detail="User has no actor id")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid actor id") from exc


def _current_actor_name(principal: dict) -> str:
    return (
        str(principal.get("nickname") or principal.get("username") or principal.get("service_name") or "")
        .strip()
        or "unknown"
    )


def _parse_date_bound(value: Optional[str], *, end_of_day: bool) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=MSK)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {value}") from exc
    if end_of_day:
        return parsed.replace(hour=23, minute=59, second=59)
    return parsed


def _status_label(status: str) -> str:
    if status == WorkflowStatus.DRAFT.value:
        return "Черновик"
    if status == WorkflowStatus.PENDING.value:
        return "К выдаче"
    if status == WorkflowStatus.ISSUED.value:
        return "Выдано"
    return status


def _status_date(record: dict[str, Any]) -> Optional[datetime]:
    status = str(record.get("status") or "")
    if status == WorkflowStatus.ISSUED.value:
        return record.get("issued_at") or record.get("created_at")
    if status == WorkflowStatus.PENDING.value:
        return record.get("reviewed_at") or record.get("created_at")
    return record.get("created_at")


def _build_command(record: dict[str, Any]) -> str:
    punishment_type = str(record.get("punishment_type") or record.get("removal_type") or "")
    command = "/unjail" if punishment_type == PunishmentRemovalType.UNJAIL.value else "/unmute"
    static_value = int(record.get("static") or record.get("violator_static") or 0)
    actor_name = (
        record.get("issued_by_name")
        or record.get("issuer_name")
        or record.get("assistant_name")
        or record.get("created_by_name")
        or "unknown"
    )
    return f"{command} {static_value} {record['reason']} by {actor_name}"


def _can_edit_delete(record: dict[str, Any], principal: dict) -> bool:
    current_actor_id = _current_actor_id(principal)
    can_manage_any = _has_permission(principal, "removals.manage.any")
    can_manage_self = _has_permission(principal, "removals.manage.self")
    status = str(record.get("status") or "")
    is_author = int(record.get("assistant_id") or 0) == current_actor_id
    if status == WorkflowStatus.DRAFT.value:
        return can_manage_self and is_author
    if status == WorkflowStatus.PENDING.value:
        return can_manage_any or (can_manage_self and is_author)
    if status == WorkflowStatus.ISSUED.value:
        return can_manage_any
    return False


def _can_issue(record: dict[str, Any], principal: dict) -> bool:
    return (
        _has_permission(principal, "removals.issue")
        and str(record.get("status") or "") == WorkflowStatus.PENDING.value
    )


def _can_submit(record: dict[str, Any], principal: dict) -> bool:
    status = str(record.get("status") or "")
    return status in {WorkflowStatus.DRAFT.value, WorkflowStatus.PENDING.value} and _can_edit_delete(
        record, principal
    )


def _serialize_removal(record: dict[str, Any], principal: dict) -> dict[str, Any]:
    assistant_id = record.get("assistant_id") or record.get("created_by_id")
    created_by_id = record.get("created_by_id") or record.get("assistant_id")
    assistant_name = (
        record.get("assistant_name")
        or record.get("created_by_name")
        or record.get("issued_by_name")
        or record.get("issuer_name")
        or "unknown"
    )
    created_by_name = (
        record.get("created_by_name")
        or record.get("assistant_name")
        or assistant_name
    )
    static_value = record.get("static")
    if static_value is None:
        static_value = record.get("violator_static")
    payload = {
        "id": record["id"],
        "assistant_id": assistant_id,
        "assistant_name": assistant_name,
        "created_by_id": created_by_id,
        "created_by_name": created_by_name,
        "reviewed_by_id": None,
        "reviewed_by_name": None,
        "issued_by_id": record.get("issued_by_id") or record.get("issuer_id"),
        "issued_by_name": record.get("issued_by_name") or record.get("issuer_name"),
        "punishment_type": record.get("punishment_type") or record.get("removal_type"),
        "static": static_value,
        "server": record["server"],
        "reason": record["reason"],
        "message_link": record.get("message_link"),
        "status": record["status"],
        "created_at": record["created_at"],
        "reviewed_at": record.get("reviewed_at"),
        "issued_at": record.get("issued_at"),
        "status_label": _status_label(str(record.get("status") or "")),
        "status_date": _status_date(record),
        "command": _build_command(record),
        "can_edit": _can_edit_delete(record, principal),
        "can_delete": _can_edit_delete(record, principal),
        "can_issue": _can_issue(record, principal),
        "can_submit": _can_submit(record, principal),
    }
    return PunishmentRemovalRecord.model_validate(payload).model_dump(mode="json")


def _ensure_view_permission(record: dict[str, Any], principal: dict) -> None:
    status = str(record.get("status") or "")
    current_actor_id = _current_actor_id(principal)
    if status == WorkflowStatus.DRAFT.value:
        if int(record.get("assistant_id") or 0) != current_actor_id:
            raise HTTPException(status_code=403, detail="Можно просматривать только свои черновики")
        if not _has_permission(principal, "removals.queue.view"):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return

    if status == WorkflowStatus.PENDING.value:
        if not _has_permission(principal, "removals.queue.view"):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return

    if status == WorkflowStatus.ISSUED.value:
        if not (
            _has_permission(principal, "removals.history.view")
            or _has_permission(principal, "removals.manage.any")
        ):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return

    raise HTTPException(status_code=404, detail="Снятие не найдено")


def _ensure_manage_permission(record: dict[str, Any], principal: dict) -> bool:
    can_manage_any = _has_permission(principal, "removals.manage.any")
    if not _can_edit_delete(record, principal):
        if can_manage_any and str(record.get("status") or "") == WorkflowStatus.DRAFT.value:
            raise HTTPException(status_code=403, detail="Чужие черновики редактировать нельзя")
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return can_manage_any


async def _validate_game_server(
    db: "Database",
    server_id: int,
    *,
    allow_inactive: bool = False,
    current_server_id: int | None = None,
) -> dict[str, Any]:
    server = await db.get_game_server(int(server_id), include_inactive=True)
    if not server:
        raise HTTPException(status_code=422, detail="Сервер не найден")
    if not bool(server.get("is_active")) and not allow_inactive:
        if current_server_id is None or int(current_server_id) != int(server_id):
            raise HTTPException(status_code=422, detail="Сервер неактивен")
    return server


async def _get_removal_or_404(db: "Database", removal_id: int) -> dict[str, Any]:
    record = await db.get_punishment_removal(removal_id)
    if not record:
        raise HTTPException(status_code=404, detail="Снятие не найдено")
    return record


async def _log_action(
    *,
    db: "Database",
    principal: dict,
    request: Request,
    removal_id: int,
    action: str,
    payload: dict[str, Any],
) -> None:
    await db.log_admin_action_v2(
        actor_name=_current_actor_name(principal),
        actor_role=principal.get("role"),
        action=action,
        target_type="removal",
        target_id=str(removal_id),
        details={
            "summary": f"{action} removal #{removal_id}",
            "payload": payload,
            "meta": {
                "request_path": str(request.url.path),
                "method": request.method,
                "actor_id": principal.get("id"),
            },
        },
        trace_id=get_trace_id(request),
    )


@router.post("")
async def create_removal(
    request: Request,
    payload: PunishmentRemovalCreate,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("removals.create")),
):
    trace_id = get_trace_id(request)
    await _validate_game_server(db, payload.server, allow_inactive=False)
    record = await db.create_punishment_removal(
        assistant_id=_current_actor_id(principal),
        assistant_name=_current_actor_name(principal),
        removal_type=payload.punishment_type.value,
        violator_static=payload.static,
        server=payload.server,
        reason=payload.reason.value,
        message_link=payload.message_link,
        target_status=payload.target_status.value,
    )
    if not record:
        raise HTTPException(status_code=500, detail="Не удалось создать снятие")

    return JSONResponse(
        content=success_envelope(
            data=_serialize_removal(record, principal),
            message="Снятие создано",
            code="REMOVAL_CREATED",
            trace_id=trace_id,
        )
    )


@router.get("/queue")
async def get_removals_queue(
    request: Request,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("removals.queue.view")),
):
    trace_id = get_trace_id(request)
    records = await db.list_punishment_removals_queue(_current_actor_id(principal))
    return JSONResponse(
        content=success_envelope(
            data=[_serialize_removal(record, principal) for record in records],
            message=f"Found {len(records)} queue removals",
            trace_id=trace_id,
        )
    )


@router.get("/history")
async def get_removals_history(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    static: Optional[int] = Query(None, ge=1),
    server: Optional[int] = Query(None, ge=1),
    removal_type: Optional[PunishmentRemovalType] = Query(None),
    assistant_name: Optional[str] = Query(None),
    issuer_name: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("removals.history.view")),
):
    trace_id = get_trace_id(request)
    offset = (page - 1) * limit
    filters: dict[str, Any] = {}
    if static is not None:
        filters["violator_static"] = static
    if server is not None:
        await _validate_game_server(db, server, allow_inactive=True)
        filters["server"] = server
    if removal_type is not None:
        filters["removal_type"] = removal_type.value
    if assistant_name:
        filters["assistant_name"] = assistant_name
    if issuer_name:
        filters["issuer_name"] = issuer_name
    parsed_from = _parse_date_bound(date_from, end_of_day=False)
    parsed_to = _parse_date_bound(date_to, end_of_day=True)
    if parsed_from:
        filters["date_from"] = parsed_from
    if parsed_to:
        filters["date_to"] = parsed_to

    result = await db.get_punishment_removals_history(limit=limit, offset=offset, filters=filters)
    total = int(result.get("total", 0))
    pages = ceil(total / limit) if total > 0 else 1
    items = [_serialize_removal(record, principal) for record in result.get("items", [])]

    return JSONResponse(
        content=success_envelope(
            data=PunishmentRemovalHistoryResponse(
                items=items,
                total=total,
                page=page,
                pages=pages,
            ).model_dump(mode="json"),
            message=f"Found {total} issued removals",
            trace_id=trace_id,
        )
    )


@router.get("/{removal_id}")
async def get_removal_detail(
    request: Request,
    removal_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(get_current_principal),
):
    trace_id = get_trace_id(request)
    record = await _get_removal_or_404(db, removal_id)
    _ensure_view_permission(record, principal)
    return JSONResponse(
        content=success_envelope(
            data=_serialize_removal(record, principal),
            message="Removal detail loaded",
            trace_id=trace_id,
        )
    )


@router.patch("/{removal_id}")
async def update_removal(
    request: Request,
    removal_id: int,
    payload: PunishmentRemovalUpdate,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(get_current_principal),
):
    trace_id = get_trace_id(request)
    existing = await _get_removal_or_404(db, removal_id)
    can_manage_any = _ensure_manage_permission(existing, principal)

    if (
        str(existing.get("status") or "") == WorkflowStatus.ISSUED.value
        and payload.target_status is not None
    ):
        raise HTTPException(status_code=403, detail="Выданное снятие нельзя вернуть в очередь")

    if "server" in payload.model_fields_set and payload.server is not None:
        await _validate_game_server(
            db,
            payload.server,
            allow_inactive=False,
            current_server_id=int(existing["server"]),
        )

    updates: dict[str, Any] = {}
    if "punishment_type" in payload.model_fields_set and payload.punishment_type is not None:
        updates["removal_type"] = payload.punishment_type.value
    if "static" in payload.model_fields_set:
        updates["violator_static"] = payload.static
    if "server" in payload.model_fields_set:
        updates["server"] = payload.server
    if "reason" in payload.model_fields_set:
        updates["reason"] = payload.reason.value if payload.reason is not None else None
    if "message_link" in payload.model_fields_set:
        updates["message_link"] = payload.message_link
    if "target_status" in payload.model_fields_set and payload.target_status is not None:
        updates["target_status"] = payload.target_status.value

    updated = await db.update_punishment_removal(removal_id, updates)
    if not updated:
        return JSONResponse(
            status_code=404,
            content=not_found_envelope(
                message="Снятие не найдено",
                code="REMOVAL_NOT_FOUND",
                trace_id=trace_id,
            ),
        )

    if can_manage_any:
        await _log_action(
            db=db,
            principal=principal,
            request=request,
            removal_id=removal_id,
            action="removal.update",
            payload=payload.model_dump(exclude_unset=True, mode="json"),
        )

    return JSONResponse(
        content=success_envelope(
            data=_serialize_removal(updated, principal),
            message="Снятие обновлено",
            code="REMOVAL_UPDATED",
            trace_id=trace_id,
        )
    )


@router.delete("/{removal_id}")
async def delete_removal(
    request: Request,
    removal_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(get_current_principal),
):
    trace_id = get_trace_id(request)
    existing = await _get_removal_or_404(db, removal_id)
    can_manage_any = _ensure_manage_permission(existing, principal)

    deleted = await db.delete_punishment_removal(removal_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content=not_found_envelope(
                message="Снятие не найдено",
                code="REMOVAL_NOT_FOUND",
                trace_id=trace_id,
            ),
        )

    if can_manage_any:
        await _log_action(
            db=db,
            principal=principal,
            request=request,
            removal_id=removal_id,
            action="removal.delete",
            payload={
                "server": existing.get("server"),
                "status": existing.get("status"),
                "assistant_name": existing.get("assistant_name"),
            },
        )

    return JSONResponse(
        content=success_envelope(
            data={"id": str(removal_id)},
            message="Снятие удалено",
            code="REMOVAL_DELETED",
            trace_id=trace_id,
        )
    )


@router.post("/{removal_id}/issue")
async def issue_removal(
    request: Request,
    removal_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("removals.issue")),
):
    trace_id = get_trace_id(request)
    existing = await _get_removal_or_404(db, removal_id)
    if str(existing.get("status") or "") != WorkflowStatus.PENDING.value:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Выдать можно только снятие со статусом К выдаче",
                code="REMOVAL_NOT_PENDING",
                trace_id=trace_id,
            ),
        )

    updated = await db.issue_punishment_removal(
        removal_id,
        issuer_id=_current_actor_id(principal),
        issuer_name=_current_actor_name(principal),
    )
    if not updated:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Не удалось выдать снятие",
                code="REMOVAL_ISSUE_CONFLICT",
                trace_id=trace_id,
            ),
        )

    await _log_action(
        db=db,
        principal=principal,
        request=request,
        removal_id=removal_id,
        action="removal.issue",
        payload={
            "status": updated.get("status"),
            "issuer_name": updated.get("issuer_name"),
        },
    )

    return JSONResponse(
        content=success_envelope(
            data=_serialize_removal(updated, principal),
            message="Снятие выдано",
            code="REMOVAL_ISSUED",
            trace_id=trace_id,
        )
    )
