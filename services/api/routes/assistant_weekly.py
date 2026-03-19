"""Routes for weekly assistant statistics read-models and admin review state."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from dependencies import require_permission
from middleware import get_trace_id
from schemas.assistant_weekly import (
    AssistantWeeklyAdminSaveRequest,
    AssistantWeeklyPayoutIssueRequest,
)
from schemas.envelope import success_envelope

if TYPE_CHECKING:
    from database import Database


router = APIRouter(tags=["Assistant Weekly"])
WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
MSK = timezone(timedelta(hours=3))


def get_db(request: Request):
    return request.app.state.database


def _today_msk_date() -> date:
    return datetime.now(MSK).date()


def _actor_name(principal: dict[str, Any]) -> str:
    return str(
        principal.get("nickname")
        or principal.get("username")
        or principal.get("service_name")
        or "unknown"
    )


def _actor_id(principal: dict[str, Any]) -> int | None:
    value = principal.get("discord_id") or principal.get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _serialize_day_labels(day_headers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for header in day_headers or []:
        weekday_index = int(header.get("weekday_index") or 0)
        labels.append(
            {
                "work_date": header.get("work_date"),
                "label": WEEKDAY_LABELS[weekday_index]
                if 0 <= weekday_index < len(WEEKDAY_LABELS)
                else str(header.get("work_date")),
            }
        )
    return labels


def _humanize_payout_reason(reason: str | None) -> str | None:
    return {
        "selected_result_not_payout_eligible": "Команда доступна только для Актив и Ультра-Актив",
        "incomplete_payout_data": "Заполни payout type, server, static и selected result",
        "payout_type_rule_missing": "Не найдена команда для выбранного payout type",
        "amount_rule_missing": "Не найдена сумма для выбранной роли и типа выплаты",
    }.get(reason, reason)


def _serialize_summary(
    item: dict[str, Any],
    *,
    week_start: date,
    week_end: date,
    include_days: bool,
) -> dict[str, Any]:
    totals = dict(item.get("totals") or {})
    counts = dict(item.get("counts") or {})
    payout = dict(item.get("payout") or {})

    days: list[dict[str, Any]] = []
    if include_days:
        for day in item.get("days") or []:
            weekday_index = int(day.get("weekday_index") or 0)
            days.append(
                {
                    "work_date": day.get("work_date"),
                    "weekday_label": WEEKDAY_LABELS[weekday_index]
                    if 0 <= weekday_index < len(WEEKDAY_LABELS)
                    else None,
                    "spec_hours_on_day": round(float(day.get("spec_hours") or 0), 4),
                    "mchat_count": int(day.get("mchat_count") or 0),
                    "complaints_count": int(day.get("complaints_count") or 0),
                    "manual_status": day.get("manual_status"),
                    "auto_status": day.get("auto_status"),
                    "resolved_status": day.get("resolved_status"),
                    "status_source": day.get("status_source") or "none",
                }
            )

    return {
        "assistant_id": str(item.get("assistant_id")),
        "nickname": item.get("nickname"),
        "role": item.get("role"),
        "week_start": week_start,
        "week_end": week_end,
        "days": days,
        "total_spec_hours": round(float(totals.get("spec_hours") or 0), 4),
        "total_mchat": int(totals.get("mchat_count") or 0),
        "total_complaints": int(totals.get("complaints_count") or 0),
        "suggested_result": item.get("suggested_result"),
        "selected_result": item.get("selected_result"),
        "result_display": item.get("result_display"),
        "count_P": int(counts.get("P") or 0),
        "count_U": int(counts.get("U") or 0),
        "count_O": int(counts.get("O") or 0),
        "payout_type": item.get("payout_type") or payout.get("type"),
        "payout_server": item.get("payout_server") or payout.get("server"),
        "payout_static": item.get("payout_static") or payout.get("static"),
        "payout_issue_status": item.get("payout_issue_status") or "pending",
        "payout_issued_at": item.get("payout_issued_at"),
        "payout_issued_by_id": (
            str(item.get("payout_issued_by_id"))
            if item.get("payout_issued_by_id") is not None
            else None
        ),
        "generated_payout_command": payout.get("command"),
        "generated_payout_available": bool(payout.get("command_available")),
        "generated_payout_reason": _humanize_payout_reason(
            payout.get("command_unavailable_reason")
        ),
    }


def _serialize_current_payload(payload: dict[str, Any]) -> dict[str, Any]:
    week_start = payload.get("week_start")
    week_end = payload.get("week_end")
    return {
        "week_start": week_start,
        "week_end": week_end,
        "day_labels": _serialize_day_labels(payload.get("day_headers") or []),
        "items": [
            _serialize_summary(
                item,
                week_start=week_start,
                week_end=week_end,
                include_days=True,
            )
            for item in payload.get("items") or []
        ],
    }


def _serialize_admin_list_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payout_options = dict(payload.get("payout_options") or {})
    week_start = payload.get("week_start")
    week_end = payload.get("week_end")
    return {
        "week_start": week_start,
        "week_end": week_end,
        "day_labels": _serialize_day_labels(payload.get("day_headers") or []),
        "items": [
            _serialize_summary(
                item,
                week_start=week_start,
                week_end=week_end,
                include_days=True,
            )
            for item in payload.get("items") or []
        ],
        "payout_types": [
            {
                "value": option.get("value"),
                "label": option.get("value"),
            }
            for option in payout_options.get("types") or []
            if option.get("value")
        ],
        "payout_servers": list(payout_options.get("servers") or []),
        "result_options": list(payout_options.get("selected_results") or []),
    }


def _serialize_detail_payload(payload: dict[str, Any]) -> dict[str, Any]:
    detail = dict(payload.get("detail") or {})
    week_start = payload.get("week_start")
    week_end = payload.get("week_end")
    summary = _serialize_summary(
        detail,
        week_start=week_start,
        week_end=week_end,
        include_days=True,
    )
    summary["day_overrides"] = [
        {
            "work_date": day.get("work_date"),
            "manual_status": day.get("manual_status"),
            "is_manual_override": (day.get("status_source") or "none") == "manual",
        }
        for day in detail.get("days") or []
    ]
    return summary


@router.get("/assistant-weekly/current")
async def get_current_weekly_assistant_stats(
    request: Request,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.view")),
):
    trace_id = get_trace_id(request)
    payload = await db.get_current_assistant_weekly_overview()
    return JSONResponse(
        content=success_envelope(
            data=jsonable_encoder(_serialize_current_payload(payload)),
            message="Недельная статистика загружена",
            trace_id=trace_id,
        )
    )


@router.get("/assistant-weekly/admin")
async def get_weekly_assistant_admin_overview(
    request: Request,
    week_start: date | None = Query(None),
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.weekly.manage")),
):
    trace_id = get_trace_id(request)
    payload = await db.get_assistant_weekly_admin_overview(week_start=week_start)
    return JSONResponse(
        content=success_envelope(
            data=jsonable_encoder(_serialize_admin_list_payload(payload)),
            message="Недельный review загружен",
            trace_id=trace_id,
        )
    )


@router.get("/assistant-weekly/admin/{assistant_id}")
async def get_weekly_assistant_admin_detail(
    request: Request,
    assistant_id: int,
    week_start: date | None = Query(None),
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.weekly.manage")),
):
    trace_id = get_trace_id(request)
    payload = await db.get_assistant_weekly_admin_detail(
        assistant_id=assistant_id,
        week_start=week_start,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Ассистент не найден для выбранной недели")
    return JSONResponse(
        content=success_envelope(
            data=jsonable_encoder(_serialize_detail_payload(payload)),
            message="Детали недели загружены",
            trace_id=trace_id,
        )
    )


@router.put("/assistant-weekly/admin/{assistant_id}")
async def save_weekly_assistant_admin_detail(
    request: Request,
    assistant_id: int,
    data: AssistantWeeklyAdminSaveRequest,
    week_start: date | None = Query(None),
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.weekly.manage")),
):
    trace_id = get_trace_id(request)
    try:
        payload = await db.save_assistant_weekly_admin_review(
            assistant_id=assistant_id,
            week_start=week_start or _today_msk_date(),
            actor_id=_actor_id(principal),
            day_overrides=[
                {
                    "work_date": item.work_date,
                    "manual_status": item.manual_status,
                    "is_manual_override": item.is_manual_override,
                }
                for item in data.day_overrides
            ],
            selected_result=data.selected_result,
            payout_type=data.payout_type,
            payout_server=data.payout_server,
            payout_static=data.payout_static,
        )
    except ValueError as error:
        message = str(error)
        if "не найден" in message.lower():
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=400, detail=message)

    issue_transition = payload.get("payout_issue_transition")
    if issue_transition:
        await db.log_admin_action_v2(
            actor_name=_actor_name(principal),
            actor_role=principal.get("role"),
            action="assistant.weekly_payout_issue.update",
            target_type="assistant_weekly_review",
            target_id=f"{assistant_id}:{payload.get('week_start')}",
            details={
                "summary": f"Auto-reset payout issuance for assistant {assistant_id}",
                "payload": jsonable_encoder(
                    {
                        "assistant_id": assistant_id,
                        "week_start": payload.get("week_start"),
                        **issue_transition,
                    }
                ),
                "meta": {
                    "trace_id": trace_id,
                    "actor_id": _actor_id(principal),
                    "request_path": str(request.url.path),
                    "method": request.method,
                },
            },
        )

    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="assistant.weekly_review.save",
        target_type="assistant_weekly_review",
        target_id=f"{assistant_id}:{payload.get('week_start')}",
        details={
            "summary": f"Saved weekly review for assistant {assistant_id}",
            "payload": jsonable_encoder(
                {
                    "assistant_id": assistant_id,
                    "week_start": payload.get("week_start"),
                    "selected_result": data.selected_result,
                    "payout_type": data.payout_type,
                    "payout_server": data.payout_server,
                    "payout_static": data.payout_static,
                    "day_overrides": [
                        {
                            "work_date": item.work_date,
                            "manual_status": item.manual_status,
                            "is_manual_override": item.is_manual_override,
                        }
                        for item in data.day_overrides
                    ],
                }
            ),
            "meta": {
                "trace_id": trace_id,
                "actor_id": _actor_id(principal),
                "request_path": str(request.url.path),
                "method": request.method,
            },
        },
    )

    return JSONResponse(
        content=success_envelope(
            data=jsonable_encoder(_serialize_detail_payload(payload)),
            message="Недельная статистика сохранена",
            code="ASSISTANT_WEEKLY_REVIEW_SAVED",
            trace_id=trace_id,
        )
    )


@router.put("/assistant-weekly/admin/{assistant_id}/payout-issue")
async def update_weekly_assistant_payout_issue_status(
    request: Request,
    assistant_id: int,
    data: AssistantWeeklyPayoutIssueRequest,
    week_start: date | None = Query(None),
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.weekly.manage")),
):
    trace_id = get_trace_id(request)
    try:
        payload = await db.save_assistant_weekly_payout_issue_status(
            assistant_id=assistant_id,
            week_start=week_start or _today_msk_date(),
            actor_id=_actor_id(principal),
            payout_issue_status=data.status,
        )
    except ValueError as error:
        message = str(error)
        if "не найден" in message.lower():
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=400, detail=message)

    issue_transition = payload.get("payout_issue_transition")
    if issue_transition and issue_transition.get("from_status") != issue_transition.get("to_status"):
        await db.log_admin_action_v2(
            actor_name=_actor_name(principal),
            actor_role=principal.get("role"),
            action="assistant.weekly_payout_issue.update",
            target_type="assistant_weekly_review",
            target_id=f"{assistant_id}:{payload.get('week_start')}",
            details={
                "summary": f"Updated payout issuance for assistant {assistant_id}",
                "payload": jsonable_encoder(
                    {
                        "assistant_id": assistant_id,
                        "week_start": payload.get("week_start"),
                        **issue_transition,
                    }
                ),
                "meta": {
                    "trace_id": trace_id,
                    "actor_id": _actor_id(principal),
                    "request_path": str(request.url.path),
                    "method": request.method,
                },
            },
        )

    return JSONResponse(
        content=success_envelope(
            data=jsonable_encoder(_serialize_detail_payload(payload)),
            message="Статус выдачи обновлён",
            code="ASSISTANT_WEEKLY_PAYOUT_ISSUE_UPDATED",
            trace_id=trace_id,
        )
    )
