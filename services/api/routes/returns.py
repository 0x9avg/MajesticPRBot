"""Routes for punishment returns workflow."""

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
from schemas.enums import PunishmentReturnStatus, PunishmentType
from schemas.returns import PunishmentReturnCreate, PunishmentReturnRecord, PunishmentReturnUpdate

router = APIRouter(prefix="/returns", tags=["Returns"])

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


def _is_ready(record: dict[str, Any]) -> bool:
    removed_at = record.get("removed_at")
    if not isinstance(removed_at, datetime):
        return False
    if removed_at.tzinfo is None:
        removed_at = removed_at.replace(tzinfo=MSK)
    return datetime.now(MSK) >= removed_at + timedelta(hours=12)


def _format_status_label(record: dict[str, Any]) -> str:
    status = str(record.get("status") or "")
    if status == PunishmentReturnStatus.CLAIMED.value:
        return f"В работе: {record.get('claimed_by_name') or 'unknown'}"
    if status == PunishmentReturnStatus.COMPLETED.value:
        return "Выполнено"

    removed_at = record.get("removed_at")
    if not isinstance(removed_at, datetime):
        return "Ожидает"
    if removed_at.tzinfo is None:
        removed_at = removed_at.replace(tzinfo=MSK)
    ready_at = removed_at + timedelta(hours=12)
    if datetime.now(MSK) >= ready_at:
        return "Готово"
    return f"Ждет до {ready_at.strftime('%d.%m %H:%M')}"


def _build_remove_command(record: dict[str, Any]) -> str:
    punishment_type = str(record.get("punishment_type") or "")
    command = "/unjail" if punishment_type == PunishmentType.JAIL.value else "/unmute"
    return f"{command} {int(record['static'])} {record['remove_reason']} by {record['removed_by_name']}"


def _build_return_command(record: dict[str, Any], viewer_name: str) -> str:
    punishment_type = str(record.get("punishment_type") or "")
    command = "/ajail" if punishment_type == PunishmentType.JAIL.value else "/mute"
    executor_name = (
        record.get("completed_by_name")
        or record.get("claimed_by_name")
        or viewer_name
    )
    return (
        f"{command} {int(record['static'])} {int(record['duration']) * 2} "
        f"Возврат наказания by {executor_name}"
    )


def _serialize_return_record(record: dict[str, Any], principal: dict) -> dict[str, Any]:
    current_actor_id = _current_actor_id(principal)
    current_actor_name = _current_actor_name(principal)
    can_manage_any = _has_permission(principal, "returns.manage.any")
    can_manage_self = _has_permission(principal, "returns.manage.self")
    can_execute = _has_permission(principal, "returns.process")

    status = str(record.get("status") or "")
    is_author = int(record.get("removed_by_id") or 0) == current_actor_id
    can_edit = can_manage_any or (
        can_manage_self and is_author and status == PunishmentReturnStatus.PENDING.value
    )
    can_delete = can_edit
    can_claim = (
        can_execute
        and status == PunishmentReturnStatus.PENDING.value
        and _is_ready(record)
    )
    can_complete = can_execute and status == PunishmentReturnStatus.CLAIMED.value and (
        can_manage_any or int(record.get("claimed_by_id") or 0) == current_actor_id
    )
    can_release = can_execute and status == PunishmentReturnStatus.CLAIMED.value and (
        int(record.get("claimed_by_id") or 0) == current_actor_id
    )

    payload = {
        **record,
        "status_label": _format_status_label(record),
        "remove_command": _build_remove_command(record),
        "return_command": _build_return_command(record, current_actor_name),
        "can_claim": can_claim,
        "can_complete": can_complete,
        "can_release": can_release,
        "can_edit": can_edit,
        "can_delete": can_delete,
    }
    return PunishmentReturnRecord.model_validate(payload).model_dump(mode="json")


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


def _ensure_manage_permission(principal: dict) -> None:
    if not (
        _has_permission(principal, "returns.manage.self")
        or _has_permission(principal, "returns.manage.any")
    ):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для управления возвратами",
        )


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


async def _get_existing_return_or_404(db: "Database", return_id: int) -> dict[str, Any]:
    record = await db.get_punishment_return(return_id)
    if not record:
        raise HTTPException(status_code=404, detail="Возврат не найден")
    return record


@router.post("")
async def create_punishment_return(
    request: Request,
    payload: PunishmentReturnCreate,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("returns.create")),
):
    trace_id = get_trace_id(request)
    await _validate_game_server(db, payload.server, allow_inactive=False)
    record = await db.create_punishment_return(
        punishment_type=payload.punishment_type.value,
        static=payload.static,
        server=payload.server,
        duration=payload.duration,
        remove_reason=payload.remove_reason.value,
        discord_message_url=payload.discord_message_url,
        removed_by_id=_current_actor_id(principal),
        removed_by_name=_current_actor_name(principal),
    )
    if not record:
        raise HTTPException(status_code=500, detail="Не удалось создать возврат")

    return JSONResponse(
        content=success_envelope(
            data=_serialize_return_record(record, principal),
            message="Возврат создан",
            code="RETURN_CREATED",
            trace_id=trace_id,
        )
    )


@router.get("/queue")
async def get_returns_queue(
    request: Request,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("returns.queue.view")),
):
    trace_id = get_trace_id(request)
    records = await db.list_punishment_returns_queue()
    return JSONResponse(
        content=success_envelope(
            data=[_serialize_return_record(record, principal) for record in records],
            message=f"Found {len(records)} active returns",
            trace_id=trace_id,
        )
    )


@router.get("/history")
async def get_returns_history(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    static: Optional[int] = Query(None, ge=1),
    server: Optional[int] = Query(None, ge=1),
    punishment_type: Optional[PunishmentType] = Query(None),
    removed_by: Optional[str] = Query(None),
    completed_by: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("returns.history.view")),
):
    trace_id = get_trace_id(request)
    offset = (page - 1) * limit
    filters: dict[str, Any] = {}
    if static is not None:
        filters["static"] = static
    if server is not None:
        await _validate_game_server(db, server, allow_inactive=True)
        filters["server"] = server
    if punishment_type is not None:
        filters["punishment_type"] = punishment_type.value
    if removed_by:
        filters["removed_by_name"] = removed_by
    if completed_by:
        filters["completed_by_name"] = completed_by
    parsed_from = _parse_date_bound(date_from, end_of_day=False)
    parsed_to = _parse_date_bound(date_to, end_of_day=True)
    if parsed_from:
        filters["date_from"] = parsed_from
    if parsed_to:
        filters["date_to"] = parsed_to

    result = await db.get_punishment_return_history(
        limit=limit,
        offset=offset,
        filters=filters,
    )
    total = int(result.get("total", 0))
    pages = ceil(total / limit) if total > 0 else 1
    items = [
        _serialize_return_record(record, principal)
        for record in result.get("items", [])
    ]

    return JSONResponse(
        content=success_envelope(
            data={
                "items": items,
                "total": total,
                "page": page,
                "pages": pages,
            },
            message=f"Found {total} completed returns",
            trace_id=trace_id,
        )
    )


@router.post("/{return_id}/claim")
async def claim_return(
    request: Request,
    return_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("returns.process")),
):
    trace_id = get_trace_id(request)
    existing = await _get_existing_return_or_404(db, return_id)
    if str(existing.get("status")) != PunishmentReturnStatus.PENDING.value:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Возврат уже взят в работу или завершен",
                code="RETURN_ALREADY_CLAIMED",
                trace_id=trace_id,
            ),
        )
    if not _is_ready(existing):
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Возврат еще не готов к выдаче",
                code="RETURN_NOT_READY",
                trace_id=trace_id,
            ),
        )

    record = await db.claim_punishment_return(
        return_id,
        claimed_by_id=_current_actor_id(principal),
        claimed_by_name=_current_actor_name(principal),
    )
    if not record:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Возврат уже взят другим ассистентом",
                code="RETURN_CLAIM_CONFLICT",
                trace_id=trace_id,
            ),
        )

    return JSONResponse(
        content=success_envelope(
            data=_serialize_return_record(record, principal),
            message="Возврат взят в работу",
            code="RETURN_CLAIMED",
            trace_id=trace_id,
        )
    )


@router.post("/{return_id}/complete")
async def complete_return(
    request: Request,
    return_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("returns.process")),
):
    trace_id = get_trace_id(request)
    existing = await _get_existing_return_or_404(db, return_id)
    if str(existing.get("status")) != PunishmentReturnStatus.CLAIMED.value:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Возврат не находится в работе",
                code="RETURN_NOT_CLAIMED",
                trace_id=trace_id,
            ),
        )

    can_manage_any = _has_permission(principal, "returns.manage.any")
    current_actor_id = _current_actor_id(principal)
    if not can_manage_any and int(existing.get("claimed_by_id") or 0) != current_actor_id:
        raise HTTPException(
            status_code=403,
            detail="Завершить возврат может только взявший его ассистент",
        )

    record = await db.complete_punishment_return(
        return_id,
        completed_by_id=current_actor_id,
        completed_by_name=_current_actor_name(principal),
        claimer_only=not can_manage_any,
    )
    if not record:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Не удалось завершить возврат",
                code="RETURN_COMPLETE_CONFLICT",
                trace_id=trace_id,
            ),
        )

    return JSONResponse(
        content=success_envelope(
            data=_serialize_return_record(record, principal),
            message="Возврат завершен",
            code="RETURN_COMPLETED",
            trace_id=trace_id,
        )
    )


@router.post("/{return_id}/release")
async def release_return(
    request: Request,
    return_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("returns.process")),
):
    trace_id = get_trace_id(request)
    existing = await _get_existing_return_or_404(db, return_id)
    if str(existing.get("status")) != PunishmentReturnStatus.CLAIMED.value:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Возврат не находится в работе",
                code="RETURN_NOT_CLAIMED",
                trace_id=trace_id,
            ),
        )

    current_actor_id = _current_actor_id(principal)
    if int(existing.get("claimed_by_id") or 0) != current_actor_id:
        raise HTTPException(
            status_code=403,
            detail="Отпустить возврат может только взявший его ассистент",
        )

    record = await db.release_punishment_return(
        return_id,
        claimed_by_id=current_actor_id,
        claimer_only=True,
    )
    if not record:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Не удалось отпустить возврат",
                code="RETURN_RELEASE_CONFLICT",
                trace_id=trace_id,
            ),
        )

    return JSONResponse(
        content=success_envelope(
            data=_serialize_return_record(record, principal),
            message="Возврат возвращен в очередь",
            code="RETURN_RELEASED",
            trace_id=trace_id,
        )
    )


@router.patch("/{return_id}")
async def update_return(
    request: Request,
    return_id: int,
    payload: PunishmentReturnUpdate,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(get_current_principal),
):
    trace_id = get_trace_id(request)
    _ensure_manage_permission(principal)
    existing = await _get_existing_return_or_404(db, return_id)

    current_actor_id = _current_actor_id(principal)
    can_manage_any = _has_permission(principal, "returns.manage.any")
    if not can_manage_any:
        if not _has_permission(principal, "returns.manage.self"):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        if str(existing.get("status")) != PunishmentReturnStatus.PENDING.value:
            raise HTTPException(
                status_code=403,
                detail="Нельзя редактировать возврат после взятия в работу",
            )
        if int(existing.get("removed_by_id") or 0) != current_actor_id:
            raise HTTPException(status_code=403, detail="Можно редактировать только свои возвраты")

    if "server" in payload.model_fields_set and payload.server is not None:
        await _validate_game_server(
            db,
            payload.server,
            allow_inactive=False,
            current_server_id=int(existing.get("server") or 0),
        )

    updated = await db.update_punishment_return(
        return_id,
        payload.model_dump(exclude_unset=True, mode="json"),
    )
    if not updated:
        return JSONResponse(
            status_code=404,
            content=not_found_envelope(
                message="Возврат не найден",
                code="RETURN_NOT_FOUND",
                trace_id=trace_id,
            ),
        )

    if can_manage_any:
        await db.log_admin_action_v2(
            actor_name=_current_actor_name(principal),
            actor_role=principal.get("role"),
            action="return.update",
            target_type="return",
            target_id=str(return_id),
            details={
                "summary": f"Updated return #{return_id}",
                "payload": payload.model_dump(exclude_unset=True, mode="json"),
                "meta": {
                    "request_path": str(request.url.path),
                    "method": request.method,
                    "actor_id": principal.get("id"),
                },
            },
        )

    return JSONResponse(
        content=success_envelope(
            data=_serialize_return_record(updated, principal),
            message="Возврат обновлен",
            code="RETURN_UPDATED",
            trace_id=trace_id,
        )
    )


@router.delete("/{return_id}")
async def delete_return(
    request: Request,
    return_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(get_current_principal),
):
    trace_id = get_trace_id(request)
    _ensure_manage_permission(principal)
    existing = await _get_existing_return_or_404(db, return_id)

    current_actor_id = _current_actor_id(principal)
    can_manage_any = _has_permission(principal, "returns.manage.any")
    if not can_manage_any:
        if not _has_permission(principal, "returns.manage.self"):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        if str(existing.get("status")) != PunishmentReturnStatus.PENDING.value:
            raise HTTPException(
                status_code=403,
                detail="Нельзя удалить возврат после взятия в работу",
            )
        if int(existing.get("removed_by_id") or 0) != current_actor_id:
            raise HTTPException(status_code=403, detail="Можно удалить только свои возвраты")

    deleted = await db.delete_punishment_return(return_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content=not_found_envelope(
                message="Возврат не найден",
                code="RETURN_NOT_FOUND",
                trace_id=trace_id,
            ),
        )

    if can_manage_any:
        await db.log_admin_action_v2(
            actor_name=_current_actor_name(principal),
            actor_role=principal.get("role"),
            action="return.delete",
            target_type="return",
            target_id=str(return_id),
            details={
                "summary": f"Deleted return #{return_id}",
                "payload": {
                    "static": existing.get("static"),
                    "server": existing.get("server"),
                    "removed_by_name": existing.get("removed_by_name"),
                    "status": existing.get("status"),
                },
                "meta": {
                    "request_path": str(request.url.path),
                    "method": request.method,
                    "actor_id": principal.get("id"),
                },
            },
        )

    return JSONResponse(
        content=success_envelope(
            data={"id": str(return_id)},
            message="Возврат удален",
            code="RETURN_DELETED",
            trace_id=trace_id,
        )
    )
