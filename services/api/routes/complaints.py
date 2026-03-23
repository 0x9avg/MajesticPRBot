"""Routes for complaints workflow."""

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
from schemas.complaints import (
    ComplaintCreate,
    ComplaintDetailRecord,
    ComplaintHistoryResponse,
    ComplaintPunishmentRecord,
    ComplaintQueueItem,
    ComplaintUpdate,
)
from schemas.envelope import conflict_envelope, not_found_envelope, success_envelope
from schemas.enums import ComplaintPunishmentType, ComplaintStatus, WorkflowTargetStatus

router = APIRouter(prefix="/complaints", tags=["Complaints"])

MSK = timezone(timedelta(hours=3))

COMPLAINT_RULES: dict[str, dict[str, str | bool]] = {
    ComplaintPunishmentType.MUTE.value: {
        "command": "/mute",
        "label": "Mute",
        "duration_unit": "мин",
        "duration_text_unit": "минут",
        "timed": True,
    },
    ComplaintPunishmentType.AJAIL.value: {
        "command": "/ajail",
        "label": "Ajail",
        "duration_unit": "мин",
        "duration_text_unit": "минут",
        "timed": True,
    },
    ComplaintPunishmentType.WARN.value: {
        "command": "/warn",
        "label": "Warn",
        "timed": False,
    },
    ComplaintPunishmentType.BAN.value: {
        "command": "/ban",
        "label": "Ban",
        "duration_unit": "дн",
        "duration_text_unit": "дней",
        "timed": True,
    },
    ComplaintPunishmentType.HARDBAN.value: {
        "command": "/hardban",
        "label": "HardBan",
        "duration_unit": "дн",
        "duration_text_unit": "дней",
        "timed": True,
    },
    ComplaintPunishmentType.GUNBAN.value: {
        "command": "/gunban",
        "label": "GunBan",
        "duration_unit": "ч",
        "duration_text_unit": "часов",
        "timed": True,
    },
}


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
    if status == ComplaintStatus.DRAFT.value:
        return "Черновик"
    if status == ComplaintStatus.PENDING.value:
        return "К выдаче"
    if status in {ComplaintStatus.ISSUED.value, "completed"}:
        return "Выдано"
    return status


def _status_date(record: dict[str, Any]) -> Optional[datetime]:
    status = str(record.get("status") or "")
    if status in {ComplaintStatus.ISSUED.value, "completed"}:
        return record.get("issued_at") or record.get("completed_at") or record.get("created_at")
    if status == ComplaintStatus.PENDING.value:
        return record.get("reviewed_at") or record.get("created_at")
    return record.get("created_at")


def _punishment_static(punishment: dict[str, Any]) -> int:
    return int(punishment.get("static") or punishment.get("violator_static") or 0)


def _punishment_duration(punishment: dict[str, Any]) -> Optional[int]:
    value = punishment.get("duration")
    if value is None:
        value = punishment.get("duration_value")
    return int(value) if value is not None else None


def _normalize_media(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized or "unknown"


def _format_incident_suffix(value: Any) -> str:
    if isinstance(value, datetime):
        aware = value.astimezone(MSK) if value.tzinfo else value.replace(tzinfo=MSK)
        return aware.strftime("%H:%M %d.%m")

    normalized = str(value or "").strip()
    if normalized:
        try:
            parsed = datetime.fromisoformat(normalized)
            aware = parsed.astimezone(MSK) if parsed.tzinfo else parsed.replace(tzinfo=MSK)
            return aware.strftime("%H:%M %d.%m")
        except ValueError:
            pass
    return "00:00 00.00"


def _preview_actor_name(header: dict[str, Any]) -> str:
    status = str(header.get("status") or "")
    if status in {ComplaintStatus.ISSUED.value, "completed"}:
        return str(header.get("issued_by_name") or header.get("issuer_name") or header.get("assistant_name") or "unknown")
    return str(header.get("assistant_name") or header.get("created_by_name") or "unknown")


def _build_command_line(header: dict[str, Any], punishment: dict[str, Any]) -> str:
    punishment_type = str(punishment.get("punishment_type") or "")
    rule = COMPLAINT_RULES[punishment_type]
    actor_name = _preview_actor_name(header)
    suffix = (
        f"(media-жалоба {_normalize_media(header.get('media'))} | "
        f"{_format_incident_suffix(header.get('incident_at'))})"
    )
    base = f"{rule['command']} {_punishment_static(punishment)}"
    if bool(rule.get("timed")):
        return (
            f"{base} {int(_punishment_duration(punishment) or 0)} "
            f"{punishment['reason']} {suffix} by {actor_name}"
        )
    return f"{base} {punishment['reason']} {suffix} by {actor_name}"


def _build_message_line(punishment: dict[str, Any]) -> str:
    punishment_type = str(punishment.get("punishment_type") or "")
    rule = COMPLAINT_RULES[punishment_type]
    base = f"Игрок #{_punishment_static(punishment)} получил {rule['label']}"
    if bool(rule.get("timed")):
        base += f" на {int(_punishment_duration(punishment) or 0)} {rule['duration_text_unit']}"
    return f"{base} за {punishment['reason']}"


def _can_edit_delete(record: dict[str, Any], principal: dict) -> bool:
    current_actor_id = _current_actor_id(principal)
    can_manage_any = _has_permission(principal, "complaints.manage.any")
    can_manage_self = _has_permission(principal, "complaints.manage.self")
    status = str(record.get("status") or "")
    is_author = int(record.get("assistant_id") or 0) == current_actor_id
    if status == ComplaintStatus.DRAFT.value:
        return can_manage_self and is_author
    if status == ComplaintStatus.PENDING.value:
        return can_manage_any or (can_manage_self and is_author)
    if status in {ComplaintStatus.ISSUED.value, "completed"}:
        return can_manage_any
    return False


def _can_issue(record: dict[str, Any], principal: dict) -> bool:
    return (
        _has_permission(principal, "complaints.issue")
        and str(record.get("status") or "") == ComplaintStatus.PENDING.value
    )


def _can_submit(record: dict[str, Any], principal: dict) -> bool:
    status = str(record.get("status") or "")
    return status in {ComplaintStatus.DRAFT.value, ComplaintStatus.PENDING.value} and _can_edit_delete(
        record, principal
    )


def _serialize_punishment(
    header: dict[str, Any],
    punishment: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "id": punishment["id"],
        "complaint_id": header.get("id") or header.get("complaint_id"),
        "punishment_type": punishment["punishment_type"],
        "static": _punishment_static(punishment),
        "duration": _punishment_duration(punishment),
        "reason": punishment["reason"],
        "command": _build_command_line(header, punishment),
        "message": _build_message_line(punishment),
    }
    return ComplaintPunishmentRecord.model_validate(payload).model_dump(mode="json")


def _group_complaint_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    ordered_ids: list[int] = []

    for record in records:
        complaint_id = int(record.get("complaint_id") or record.get("id") or 0)
        entry = grouped.get(complaint_id)
        if entry is None:
            entry = {
                **record,
                "id": complaint_id,
                "complaint_id": complaint_id,
                "punishments": [],
            }
            grouped[complaint_id] = entry
            ordered_ids.append(complaint_id)

        if isinstance(record.get("punishments"), list):
            entry["punishments"] = list(record.get("punishments") or [])
            continue

        punishment_id = record.get("punishment_id") or record.get("id")
        if record.get("punishment_type") is None:
            continue

        entry["punishments"].append(
            {
                "id": punishment_id,
                "complaint_id": complaint_id,
                "punishment_type": record["punishment_type"],
                "static": _punishment_static(record),
                "duration": _punishment_duration(record),
                "reason": record["reason"],
            }
        )

    return [grouped[complaint_id] for complaint_id in ordered_ids]


def _serialize_complaint_entity(record: dict[str, Any], principal: dict) -> dict[str, Any]:
    punishments = [
        _serialize_punishment(record, punishment)
        for punishment in record.get("punishments", [])
    ]
    aggregate_command = "\n".join(
        str(item.get("command") or "").strip() for item in punishments if item.get("command")
    ) or None
    aggregate_message = "\n".join(
        str(item.get("message") or "").strip() for item in punishments if item.get("message")
    ) or None
    punishments_count = int(
        record.get("punishments_count")
        or record.get("punishment_count")
        or len(punishments)
        or 1
    )
    payload = {
        "id": record.get("id") or record.get("complaint_id"),
        "complaint_id": record.get("complaint_id") or record.get("id"),
        "assistant_id": record.get("assistant_id") or record.get("created_by_id"),
        "assistant_name": record.get("assistant_name") or record.get("created_by_name"),
        "created_by_id": record.get("created_by_id") or record.get("assistant_id"),
        "created_by_name": record.get("created_by_name") or record.get("assistant_name"),
        "reviewed_by_id": record.get("reviewed_by_id"),
        "reviewed_by_name": record.get("reviewed_by_name"),
        "issued_by_id": record.get("issued_by_id") or record.get("issuer_id"),
        "issued_by_name": record.get("issued_by_name") or record.get("issuer_name"),
        "server": record["server"],
        "complaint_link": record.get("complaint_link"),
        "media": record.get("media"),
        "incident_at": record["incident_at"],
        "status": record["status"],
        "created_at": record["created_at"],
        "reviewed_at": record.get("reviewed_at"),
        "issued_at": record.get("issued_at"),
        "status_label": _status_label(str(record.get("status") or "")),
        "status_date": _status_date(record),
        "command": aggregate_command,
        "message": aggregate_message,
        "aggregate_command": aggregate_command,
        "aggregate_message": aggregate_message,
        "punishments_count": punishments_count,
        "punishments": punishments,
        "can_edit": _can_edit_delete(record, principal),
        "can_delete": _can_edit_delete(record, principal),
        "can_issue": _can_issue(record, principal),
        "can_submit": _can_submit(record, principal),
    }
    return ComplaintQueueItem.model_validate(payload).model_dump(mode="json")


def _serialize_complaint_detail(record: dict[str, Any], principal: dict) -> dict[str, Any]:
    return ComplaintDetailRecord.model_validate(
        _serialize_complaint_entity(record, principal)
    ).model_dump(mode="json")


def _ensure_view_permission(record: dict[str, Any], principal: dict) -> None:
    status = str(record.get("status") or "")
    current_actor_id = _current_actor_id(principal)
    if status == ComplaintStatus.DRAFT.value:
        if int(record.get("assistant_id") or 0) != current_actor_id:
            raise HTTPException(status_code=403, detail="Можно просматривать только свои черновики")
        if not _has_permission(principal, "complaints.queue.view"):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return

    if status == ComplaintStatus.PENDING.value:
        if not _has_permission(principal, "complaints.queue.view"):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return

    if status in {ComplaintStatus.ISSUED.value, "completed"}:
        if not (
            _has_permission(principal, "complaints.history.view")
            or _has_permission(principal, "complaints.manage.any")
        ):
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return

    raise HTTPException(status_code=404, detail="Жалоба не найдена")


def _ensure_manage_permission(record: dict[str, Any], principal: dict) -> bool:
    can_manage_any = _has_permission(principal, "complaints.manage.any")
    if not _can_edit_delete(record, principal):
        if can_manage_any and str(record.get("status") or "") == ComplaintStatus.DRAFT.value:
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


async def _get_complaint_or_404(db: "Database", complaint_id: int) -> dict[str, Any]:
    record = await db.get_complaint(complaint_id)
    if not record:
        raise HTTPException(status_code=404, detail="Жалоба не найдена")
    return record


async def _log_manage_any_action(
    *,
    db: "Database",
    principal: dict,
    request: Request,
    complaint_id: int,
    action: str,
    payload: dict[str, Any],
) -> None:
    await db.log_admin_action_v2(
        actor_name=_current_actor_name(principal),
        actor_role=principal.get("role"),
        action=action,
        target_type="complaint",
        target_id=str(complaint_id),
        details={
            "summary": f"{action} complaint #{complaint_id}",
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
async def create_complaint(
    request: Request,
    payload: ComplaintCreate,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("complaints.create")),
):
    trace_id = get_trace_id(request)
    await _validate_game_server(db, payload.server, allow_inactive=False)
    record = await db.create_complaint(
        assistant_id=_current_actor_id(principal),
        assistant_name=_current_actor_name(principal),
        server=payload.server,
        complaint_link=payload.complaint_link,
        media=payload.media,
        incident_at=payload.incident_at,
        target_status=payload.target_status.value,
        punishments=[
            {
                "punishment_type": punishment.punishment_type.value,
                "violator_static": punishment.static,
                "duration_value": punishment.duration,
                "reason": punishment.reason,
            }
            for punishment in payload.punishments
        ],
    )
    if not record:
        raise HTTPException(status_code=500, detail="Не удалось создать жалобу")

    return JSONResponse(
        content=success_envelope(
            data=_serialize_complaint_detail(record, principal),
            message="Жалоба создана",
            code="COMPLAINT_CREATED",
            trace_id=trace_id,
        )
    )


@router.get("/queue")
async def get_complaints_queue(
    request: Request,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("complaints.queue.view")),
):
    trace_id = get_trace_id(request)
    records = await db.list_complaints_queue(_current_actor_id(principal))
    complaint_records = _group_complaint_rows(list(records or []))
    return JSONResponse(
        content=success_envelope(
            data=[_serialize_complaint_entity(record, principal) for record in complaint_records],
            message=f"Found {len(complaint_records)} queue complaints",
            trace_id=trace_id,
        )
    )


@router.get("/history")
async def get_complaints_history(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    static: Optional[int] = Query(None, ge=1),
    server: Optional[int] = Query(None, ge=1),
    punishment_type: Optional[ComplaintPunishmentType] = Query(None),
    assistant_name: Optional[str] = Query(None),
    issuer_name: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("complaints.history.view")),
):
    trace_id = get_trace_id(request)
    offset = (page - 1) * limit
    filters: dict[str, Any] = {}
    if static is not None:
        filters["violator_static"] = static
    if server is not None:
        await _validate_game_server(db, server, allow_inactive=True)
        filters["server"] = server
    if punishment_type is not None:
        filters["punishment_type"] = punishment_type.value
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

    result = await db.get_complaints_history(limit=limit, offset=offset, filters=filters)
    total = int(result.get("total", 0))
    raw_items = list(result.get("items") or [])
    complaint_records = _group_complaint_rows(raw_items)
    if len(complaint_records) != len(raw_items):
        total = len(complaint_records)
    pages = ceil(total / limit) if total > 0 else 1
    items = [
        _serialize_complaint_entity(record, principal)
        for record in complaint_records
    ]
    return JSONResponse(
        content=success_envelope(
            data=ComplaintHistoryResponse(
                items=items,
                total=total,
                page=page,
                pages=pages,
            ).model_dump(mode="json"),
            message=f"Found {total} issued complaints",
            trace_id=trace_id,
        )
    )


@router.get("/{complaint_id}")
async def get_complaint_detail(
    request: Request,
    complaint_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(get_current_principal),
):
    trace_id = get_trace_id(request)
    record = await _get_complaint_or_404(db, complaint_id)
    _ensure_view_permission(record, principal)
    return JSONResponse(
        content=success_envelope(
            data=_serialize_complaint_detail(record, principal),
            message="Complaint detail loaded",
            trace_id=trace_id,
        )
    )


@router.patch("/{complaint_id}")
async def update_complaint(
    request: Request,
    complaint_id: int,
    payload: ComplaintUpdate,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(get_current_principal),
):
    trace_id = get_trace_id(request)
    existing = await _get_complaint_or_404(db, complaint_id)
    can_manage_any = _ensure_manage_permission(existing, principal)

    if (
        str(existing.get("status") or "") == ComplaintStatus.ISSUED.value
        and payload.target_status is not None
    ):
        raise HTTPException(status_code=403, detail="Выданную жалобу нельзя вернуть в очередь")

    if "server" in payload.model_fields_set and payload.server is not None:
        await _validate_game_server(
            db,
            payload.server,
            allow_inactive=False,
            current_server_id=int(existing["server"]),
        )

    header_updates = payload.model_dump(
        include={"server", "complaint_link", "media", "incident_at"},
        exclude_unset=True,
        mode="json",
    )
    punishments_payload = (
        [
            {
                "id": item.id,
                "punishment_type": item.punishment_type.value,
                "violator_static": item.static,
                "duration_value": item.duration,
                "reason": item.reason,
            }
            for item in payload.punishments
        ]
        if payload.punishments is not None
        else None
    )
    updated = await db.update_complaint(
        complaint_id,
        header_updates=header_updates,
        punishments=punishments_payload,
        target_status=payload.target_status.value if payload.target_status is not None else None,
    )
    if not updated:
        return JSONResponse(
            status_code=404,
            content=not_found_envelope(
                message="Жалоба не найдена",
                code="COMPLAINT_NOT_FOUND",
                trace_id=trace_id,
            ),
        )

    if can_manage_any:
        await _log_manage_any_action(
            db=db,
            principal=principal,
            request=request,
            complaint_id=complaint_id,
            action="complaint.update",
            payload=payload.model_dump(exclude_unset=True, mode="json"),
        )

    return JSONResponse(
        content=success_envelope(
            data=_serialize_complaint_detail(updated, principal),
            message="Жалоба обновлена",
            code="COMPLAINT_UPDATED",
            trace_id=trace_id,
        )
    )


@router.delete("/{complaint_id}")
async def delete_complaint(
    request: Request,
    complaint_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(get_current_principal),
):
    trace_id = get_trace_id(request)
    existing = await _get_complaint_or_404(db, complaint_id)
    can_manage_any = _ensure_manage_permission(existing, principal)

    deleted = await db.delete_complaint(complaint_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content=not_found_envelope(
                message="Жалоба не найдена",
                code="COMPLAINT_NOT_FOUND",
                trace_id=trace_id,
            ),
        )

    if can_manage_any:
        await _log_manage_any_action(
            db=db,
            principal=principal,
            request=request,
            complaint_id=complaint_id,
            action="complaint.delete",
            payload={
                "server": existing.get("server"),
                "status": existing.get("status"),
                "assistant_name": existing.get("assistant_name"),
            },
        )

    return JSONResponse(
        content=success_envelope(
            data={"id": str(complaint_id)},
            message="Жалоба удалена",
            code="COMPLAINT_DELETED",
            trace_id=trace_id,
        )
    )


@router.delete("/{complaint_id}/punishments/{punishment_id}")
async def delete_complaint_punishment(
    request: Request,
    complaint_id: int,
    punishment_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(get_current_principal),
):
    trace_id = get_trace_id(request)
    existing = await _get_complaint_or_404(db, complaint_id)
    can_manage_any = _ensure_manage_permission(existing, principal)

    punishments = existing.get("punishments") or []
    if len(punishments) <= 1:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Нельзя удалить последнее наказание отдельно от жалобы",
                code="COMPLAINT_LAST_PUNISHMENT",
                trace_id=trace_id,
            ),
        )

    deleted = await db.delete_complaint_punishment(complaint_id, punishment_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content=not_found_envelope(
                message="Наказание жалобы не найдено",
                code="COMPLAINT_PUNISHMENT_NOT_FOUND",
                trace_id=trace_id,
            ),
        )

    updated = await _get_complaint_or_404(db, complaint_id)

    if can_manage_any:
        await _log_manage_any_action(
            db=db,
            principal=principal,
            request=request,
            complaint_id=complaint_id,
            action="complaint.update",
            payload={"deleted_punishment_id": punishment_id},
        )

    return JSONResponse(
        content=success_envelope(
            data=_serialize_complaint_detail(updated, principal),
            message="Наказание удалено из жалобы",
            code="COMPLAINT_PUNISHMENT_DELETED",
            trace_id=trace_id,
        )
    )


@router.post("/{complaint_id}/issue")
async def issue_complaint(
    request: Request,
    complaint_id: int,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("complaints.issue")),
):
    trace_id = get_trace_id(request)
    existing = await _get_complaint_or_404(db, complaint_id)
    if str(existing.get("status") or "") != ComplaintStatus.PENDING.value:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Выдать можно только жалобу со статусом К выдаче",
                code="COMPLAINT_NOT_PENDING",
                trace_id=trace_id,
            ),
        )

    updated = await db.issue_complaint(
        complaint_id,
        issuer_id=_current_actor_id(principal),
        issuer_name=_current_actor_name(principal),
    )
    if not updated:
        return JSONResponse(
            status_code=409,
            content=conflict_envelope(
                message="Не удалось выдать жалобу",
                code="COMPLAINT_ISSUE_CONFLICT",
                trace_id=trace_id,
            ),
        )

    await _log_manage_any_action(
        db=db,
        principal=principal,
        request=request,
        complaint_id=complaint_id,
        action="complaint.issue",
        payload={
            "status": updated.get("status"),
            "issuer_name": updated.get("issuer_name"),
        },
    )

    return JSONResponse(
        content=success_envelope(
            data=_serialize_complaint_detail(updated, principal),
            message="Жалоба выдана",
            code="COMPLAINT_ISSUED",
            trace_id=trace_id,
        )
    )
