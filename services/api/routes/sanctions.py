"""Routes for sanction ledger, queue batches, day adjustments and monthly policy."""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from dependencies import require_permission
from middleware import get_trace_id
from schemas.common import Snowflake
from schemas.envelope import success_envelope
from schemas.sanctions import (
    AssistantDayMchatUpsertRequest,
    AssistantDayPointAdjustmentUpsertRequest,
    ManualSanctionCreateRequest,
    MonthlyCheckRulesReplaceRequest,
    MonthlySanctionSettingsUpdateRequest,
    SanctionOperationCreateRequest,
    SanctionOperationMemberAddRequest,
    SanctionOperationUpdateRequest,
    SanctionReliefCreateRequest,
    SanctionReplaceRequest,
    WorkoffPreviewRequest,
)
from services.outbox import publish_integration_event

if TYPE_CHECKING:
    from db import Database
    from services.broker import BrokerService


router = APIRouter(tags=["Sanctions"])
MSK = timezone(timedelta(hours=3))


def get_db(request: Request):
    return request.app.state.database


def get_broker(request: Request):
    return getattr(request.app.state, "broker", None)


def _actor_name(principal: dict[str, Any]) -> str:
    return str(principal.get("nickname") or principal.get("username") or principal.get("service_name") or "unknown")


def _actor_id(principal: dict[str, Any]) -> int | None:
    value = principal.get("discord_id") or principal.get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _today_msk_date() -> date:
    return datetime.now(MSK).date()


def _normalize_sanction_amount(kind: str, amount: float | None) -> float:
    if kind in {"check", "oral", "strict"}:
        return 1.0
    if amount is None or float(amount) <= 0:
        raise HTTPException(status_code=400, detail="Для выбранной санкции требуется положительный размер")
    return round(float(amount), 4)


def _normalize_auto_relief_date(kind: str, auto_relief_date: date | None) -> date | None:
    if kind in {"oral", "strict"}:
        if auto_relief_date is None:
            raise HTTPException(
                status_code=400,
                detail="Для устного и строгого требуется дата автоматического снятия",
            )
        return auto_relief_date
    return None


def _workoff_items_payload(items) -> list[dict[str, Any]]:
    return [
        {
            "metric": item.metric,
            "multiplier": item.multiplier,
            "period_start": item.period_start,
            "period_end": item.period_end,
        }
        for item in (items or [])
    ]


def _serialize_bigint_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_serialize_bigint_fields(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if item is None:
                result[key] = None
            elif key == "id" or key.endswith("_id"):
                result[key] = str(item)
            else:
                result[key] = _serialize_bigint_fields(item)
        return result
    return value


def _response_data(value: Any) -> Any:
    return jsonable_encoder(_serialize_bigint_fields(value))


def _operation_response(operation: dict[str, Any]) -> dict[str, Any]:
    if not operation:
        return operation
    result = dict(operation)
    if "basis_date" in result:
        result["operation_date"] = result.pop("basis_date")
    if "sanction_kind" in result:
        result["penalty_kind"] = result.pop("sanction_kind")
    if "sanction_amount" in result:
        result["penalty_amount"] = result.pop("sanction_amount")
    if "audience_mode" in result:
        result["recipient_mode"] = result.pop("audience_mode")
    if "members" in result and isinstance(result["members"], list):
        result["members"] = [_operation_member_response(member) for member in result["members"]]
    if "workoff_items" in result and isinstance(result["workoff_items"], list):
        result["workoff_items"] = [_workoff_response(item) for item in result["workoff_items"]]
    if result.get("processing_mode") == "nightly_auto" and not result.get("processed_by_name"):
        result["processed_by_name"] = "Система"
    return result


def _operation_member_response(member: dict[str, Any]) -> dict[str, Any]:
    if not member:
        return member
    result = dict(member)
    if "batch_id" in result:
        result["operation_id"] = result.pop("batch_id")
    if "execution_status" in result:
        result["issue_status"] = result.pop("execution_status")
    if "execution_reason" in result:
        result["issue_reason"] = result.pop("execution_reason")
    return result


def _workoff_response(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    if "batch_id" in result:
        result["operation_id"] = result.pop("batch_id")
    return result


def _active_sanction_response(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    if "source_batch_id" in result:
        result["operation_id"] = result.pop("source_batch_id")
    if "policy_month" in result:
        result["settings_month"] = result.pop("policy_month")
    if "cycle_no" in result:
        result["check_rule_hit_no"] = result.pop("cycle_no")
    if "workoff_items" in result and isinstance(result["workoff_items"], list):
        result["workoff_items"] = [_workoff_response(entry) for entry in result["workoff_items"]]
    if "workoff_progress_summary" in result and isinstance(result["workoff_progress_summary"], dict):
        summary = dict(result["workoff_progress_summary"])
        if "items" in summary and isinstance(summary["items"], list):
            summary["items"] = [_workoff_response(entry) for entry in summary["items"]]
        result["workoff_progress_summary"] = summary
    return result


@router.post("/assistant-day-points")
async def upsert_assistant_day_points(
    request: Request,
    data: AssistantDayPointAdjustmentUpsertRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.points.update")),
):
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(int(data.assistant_id))
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    result = await db.upsert_assistant_day_point_adjustment(
        assistant_id=int(data.assistant_id),
        work_date=data.work_date,
        delta_points=data.delta_points,
    )
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="assistant.day_points.upsert",
        target_type="assistant_day_point_adjustment",
        target_id=f"{data.assistant_id}:{data.work_date}",
        details={
            "summary": f"Set day point adjustment for assistant {data.assistant_id}",
            "payload": jsonable_encoder(result),
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
            data=_response_data(result),
            message="Дневная корректировка баллов сохранена",
            code="ASSISTANT_DAY_POINTS_SAVED",
            trace_id=trace_id,
        )
    )


@router.put("/assistant-day-mchat")
async def upsert_assistant_day_mchat(
    request: Request,
    data: AssistantDayMchatUpsertRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.points.update")),
):
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(int(data.assistant_id))
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")

    result = await db.upsert_assistant_day_mchat(
        assistant_id=int(data.assistant_id),
        work_date=data.work_date,
        mchat_count=data.mchat_count,
    )
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="assistant.day_mchat.upsert",
        target_type="assistant_day_mchat",
        target_id=f"{data.assistant_id}:{data.work_date}",
        details={
            "summary": f"Set day mchat for assistant {data.assistant_id}",
            "payload": jsonable_encoder(result),
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
            data=_response_data(result),
            message="Дневной mchat сохранен",
            code="ASSISTANT_DAY_MCHAT_SAVED",
            trace_id=trace_id,
        )
    )


@router.get("/assistants/{pr_id}/day-status")
async def get_assistant_day_status(
    request: Request,
    pr_id: Snowflake,
    date_value: date = Query(..., alias="date"),
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.view")),
):
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")
    result = await db.get_assistant_day_status(
        assistant_id=pr_id,
        work_date=date_value,
    )
    return JSONResponse(
        content=success_envelope(
            data=_response_data(result),
            message="Дневной статус получен",
            trace_id=trace_id,
        )
    )


@router.get("/assistants/{pr_id}/sanctions/summary")
async def get_assistant_sanctions_summary(
    request: Request,
    pr_id: Snowflake,
    date_value: date | None = Query(None, alias="date"),
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.view")),
):
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")
    result = await db.get_assistant_sanctions_summary(
        assistant_id=pr_id,
        as_of_date=date_value,
    )
    return JSONResponse(
        content=success_envelope(
            data=_response_data(result),
            message="Сводка санкций получена",
            trace_id=trace_id,
        )
    )


@router.get("/assistants/{pr_id}/sanctions/active")
async def get_assistant_active_sanctions(
    request: Request,
    pr_id: Snowflake,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.view")),
):
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(pr_id)
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")
    result = await db.get_assistant_active_sanctions(pr_id)
    return JSONResponse(
        content=success_envelope(
            data=_response_data([_active_sanction_response(item) for item in result]),
            message="Активные санкции получены",
            trace_id=trace_id,
        )
    )


@router.post("/assistant-sanctions")
async def create_manual_sanction(
    request: Request,
    data: ManualSanctionCreateRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    assistant = await db.get_assistant(int(data.assistant_id))
    if not assistant:
        raise HTTPException(status_code=404, detail="Ассистент не найден")
    amount = _normalize_sanction_amount(data.kind, data.amount)
    try:
        result = await db.create_manual_sanction(
            assistant_id=int(data.assistant_id),
            kind=data.kind,
            amount=amount,
            auto_relief_date=_normalize_auto_relief_date(data.kind, data.auto_relief_date),
            basis_date=_today_msk_date(),
            workoff_items=_workoff_items_payload(data.workoff_items),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="assistant.sanction.issue.manual",
        target_type="assistant",
        target_id=str(data.assistant_id),
        details={
            "summary": f"Issued manual sanction for assistant {data.assistant_id}",
            "payload": jsonable_encoder({"request": data.model_dump(mode="json"), "normalized_amount": amount, "result": result}),
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
            data=_response_data(result),
            message="Санкция выдана",
            code="SANCTION_ISSUED",
            trace_id=trace_id,
        )
    )


@router.post("/assistant-sanctions/{sanction_id}/reliefs")
async def add_sanction_relief(
    request: Request,
    sanction_id: Snowflake,
    data: SanctionReliefCreateRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    try:
        result = await db.add_sanction_relief(
            sanction_id=sanction_id,
            amount=data.amount,
            relief_type=data.relief_type,
            basis_date=data.basis_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Санкция не найдена или уже снята")
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="assistant.sanction.relief.manual",
        target_type="sanction",
        target_id=str(sanction_id),
        details={
            "summary": f"Added relief for sanction {sanction_id}",
            "payload": jsonable_encoder(result),
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
            data=_response_data(result),
            message="Снятие санкции записано",
            code="SANCTION_RELIEF_ADDED",
            trace_id=trace_id,
        )
    )


@router.post("/assistant-sanctions/{sanction_id}/replace")
async def replace_sanction(
    request: Request,
    sanction_id: Snowflake,
    data: SanctionReplaceRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    try:
        result = await db.replace_sanction(
            sanction_id=sanction_id,
            new_kind=data.new_kind,
            new_amount=_normalize_sanction_amount(data.new_kind, data.new_amount),
            new_auto_relief_date=_normalize_auto_relief_date(
                data.new_kind, data.new_auto_relief_date
            ),
            basis_date=data.basis_date,
            workoff_items=_workoff_items_payload(data.workoff_items),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Санкция не найдена")
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="assistant.sanction.replace",
        target_type="sanction",
        target_id=str(sanction_id),
        details={
            "summary": f"Replaced sanction {sanction_id}",
            "payload": jsonable_encoder({"request": data.model_dump(mode="json"), "result": result}),
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
            data=_response_data(result),
            message="Санкция заменена",
            code="SANCTION_REPLACED",
            trace_id=trace_id,
        )
    )


@router.get("/sanctions/{sanction_id}/workoff-progress")
async def get_sanction_workoff_progress(
    request: Request,
    sanction_id: Snowflake,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.view")),
):
    trace_id = get_trace_id(request)
    result = await db.get_sanction_workoff_progress(sanction_id)
    if not result:
        raise HTTPException(status_code=404, detail="Санкция не найдена")
    return JSONResponse(
        content=success_envelope(
            data=_response_data(result),
            message="Прогресс отработки получен",
            trace_id=trace_id,
        )
    )


@router.post("/sanctions/workoff-preview")
async def preview_workoff(
    request: Request,
    data: WorkoffPreviewRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    result = await db.preview_workoff_for_assistants(
        assistant_ids=[int(value) for value in data.assistant_ids],
        workoff_items=_workoff_items_payload(data.workoff_items),
    )
    return JSONResponse(
        content=success_envelope(
            data=_response_data({"assistants": result}),
            message="Предпросмотр отработки получен",
            trace_id=trace_id,
        )
    )


@router.get("/sanction-settings")
async def get_current_settings(
    request: Request,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    policy = await db.get_current_sanction_policy()
    return JSONResponse(
        content=success_envelope(
            data=_response_data(policy),
            message="Текущие настройки санкций получены",
            trace_id=trace_id,
        )
    )


@router.put("/sanction-settings")
async def put_current_settings(
    request: Request,
    data: MonthlySanctionSettingsUpdateRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    result = await db.upsert_current_sanction_policy(data.model_dump(exclude_none=True))
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="sanction.policy.update",
        target_type="sanction_policy",
        target_id="current",
        details={
            "summary": "Updated current sanction policy",
            "payload": jsonable_encoder(data.model_dump(mode="json", exclude_none=True)),
            "meta": {
                "trace_id": trace_id,
                "actor_id": _actor_id(principal),
            },
        },
    )
    return JSONResponse(
        content=success_envelope(
            data=_response_data(result),
            message="Текущие настройки санкций сохранены",
            code="SANCTION_POLICY_SAVED",
            trace_id=trace_id,
        )
    )


@router.get("/sanction-settings/check-rules")
async def get_current_check_rules(
    request: Request,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    rules = await db.get_current_check_cycle_rules()
    return JSONResponse(
        content=success_envelope(
            data=_response_data([
                {
                    "id": item.get("id"),
                    "range_start": item.get("cycle_from"),
                    "range_end": item.get("cycle_to"),
                    "penalty_kind": item.get("sanction_kind"),
                    "penalty_amount": item.get("sanction_amount"),
                }
                for item in rules
            ]),
            message="Правила галок получены",
            trace_id=trace_id,
        )
    )


@router.put("/sanction-settings/check-rules")
async def replace_current_check_rules(
    request: Request,
    data: MonthlyCheckRulesReplaceRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    payload_rules = [
        {
            "cycle_from": rule.range_start,
            "cycle_to": rule.range_end,
            "sanction_kind": rule.penalty_kind,
            "sanction_amount": rule.penalty_amount,
        }
        for rule in data.rules
    ]
    try:
        result = await db.replace_current_check_cycle_rules(payload_rules)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="sanction.settings.check_rules.replace",
        target_type="check_rules",
        target_id="current",
        details={
            "summary": "Replaced current check rules",
            "payload": jsonable_encoder(data.model_dump(mode="json")),
            "meta": {
                "trace_id": trace_id,
                "actor_id": _actor_id(principal),
            },
        },
    )
    return JSONResponse(
        content=success_envelope(
            data=_response_data([
                {
                    "id": item.get("id"),
                    "range_start": item.get("cycle_from"),
                    "range_end": item.get("cycle_to"),
                    "penalty_kind": item.get("sanction_kind"),
                    "penalty_amount": item.get("sanction_amount"),
                }
                for item in result
            ]),
            message="Правила галок сохранены",
            code="SANCTION_CHECK_RULES_SAVED",
            trace_id=trace_id,
        )
    )


@router.get("/sanction-operations")
async def list_sanction_operations(
    request: Request,
    status: str | None = Query(None),
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    batches = await db.list_queued_sanction_batches(status=status)
    return JSONResponse(
        content=success_envelope(
            data=_response_data([_operation_response(item) for item in batches]),
            message=f"Найдено {len(batches)} операций выдачи",
            trace_id=trace_id,
        )
    )


@router.post("/sanction-operations")
async def create_sanction_operation(
    request: Request,
    data: SanctionOperationCreateRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    amount = _normalize_sanction_amount(data.penalty_kind, data.penalty_amount)
    try:
        batch = await db.create_queued_sanction_batch(
            basis_date=_today_msk_date(),
            created_by_id=_actor_id(principal),
            sanction_kind=data.penalty_kind,
            sanction_amount=amount,
            auto_relief_date=_normalize_auto_relief_date(
                data.penalty_kind, data.auto_relief_date
            ),
            audience_mode=data.recipient_mode,
            assistant_ids=[int(v) for v in data.assistant_ids],
            workoff_items=_workoff_items_payload(data.workoff_items),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="sanction.operation.create",
        target_type="sanction_operation",
        target_id=str(batch["id"]),
        details={
            "summary": f"Created sanction operation {batch['id']}",
            "payload": jsonable_encoder({"request": data.model_dump(mode="json"), "normalized_amount": amount}),
            "meta": {
                "trace_id": trace_id,
                "actor_id": _actor_id(principal),
            },
        },
    )
    return JSONResponse(
        content=success_envelope(
            data=_response_data(_operation_response(batch)),
            message="Операция выдачи добавлена в очередь",
            code="SANCTION_OPERATION_CREATED",
            trace_id=trace_id,
        )
    )


@router.get("/sanction-operations/{operation_id}")
async def get_sanction_operation(
    request: Request,
    operation_id: Snowflake,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    batch = await db.get_queued_sanction_batch(operation_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Операция выдачи не найдена")
    return JSONResponse(
        content=success_envelope(
            data=_response_data(_operation_response(batch)),
            message="Операция выдачи найдена",
            trace_id=trace_id,
        )
    )


@router.patch("/sanction-operations/{operation_id}")
async def update_sanction_operation(
    request: Request,
    operation_id: Snowflake,
    data: SanctionOperationUpdateRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    payload = data.model_dump(exclude_none=True)
    existing_batch = None
    if (
        "penalty_kind" in payload
        or "penalty_amount" in payload
        or "auto_relief_date" in payload
    ):
        existing_batch = await db.get_queued_sanction_batch(operation_id)
        if not existing_batch:
            raise HTTPException(status_code=404, detail="Операция выдачи не найдена")
    if existing_batch:
        effective_kind = str(payload.get("penalty_kind") or existing_batch["sanction_kind"])
        if (
            "penalty_kind" in payload
            or "penalty_amount" in payload
            or "auto_relief_date" in payload
        ):
            payload["sanction_amount"] = _normalize_sanction_amount(
                effective_kind,
                payload.get(
                    "penalty_amount",
                    existing_batch.get("sanction_amount"),
                ),
            )
            payload["auto_relief_date"] = _normalize_auto_relief_date(
                effective_kind,
                payload.get(
                    "auto_relief_date",
                    existing_batch.get("auto_relief_date"),
                ),
            )
    if "penalty_kind" in payload:
        payload["sanction_kind"] = payload.pop("penalty_kind")
    if "penalty_amount" in payload:
        payload["sanction_amount"] = payload.pop("penalty_amount")
    if "recipient_mode" in payload:
        payload["audience_mode"] = payload.pop("recipient_mode")
    if "workoff_items" in payload:
        payload["workoff_items"] = _workoff_items_payload(data.workoff_items or [])
    try:
        result = await db.update_queued_sanction_batch(batch_id=operation_id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Операция выдачи не найдена")
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="sanction.operation.update",
        target_type="sanction_operation",
        target_id=str(operation_id),
        details={
            "summary": f"Updated sanction operation {operation_id}",
            "payload": jsonable_encoder(data.model_dump(mode="json", exclude_none=True)),
            "meta": {"trace_id": trace_id, "actor_id": _actor_id(principal)},
        },
    )
    return JSONResponse(
        content=success_envelope(
            data=_response_data(_operation_response(result)),
            message="Операция выдачи обновлена",
            code="SANCTION_OPERATION_UPDATED",
            trace_id=trace_id,
        )
    )


@router.post("/sanction-operations/{operation_id}/members")
async def add_operation_member(
    request: Request,
    operation_id: Snowflake,
    data: SanctionOperationMemberAddRequest,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    try:
        result = await db.add_queued_batch_member(
            batch_id=operation_id,
            assistant_id=int(data.assistant_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Операция выдачи не найдена")
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="sanction.operation.member.add",
        target_type="sanction_operation",
        target_id=str(operation_id),
        details={
            "summary": f"Added assistant {data.assistant_id} to sanction operation {operation_id}",
            "meta": {"trace_id": trace_id, "actor_id": _actor_id(principal)},
        },
    )
    return JSONResponse(
        content=success_envelope(
            data=_response_data(_operation_response(result)),
            message="Ассистент добавлен в операцию",
            trace_id=trace_id,
        )
    )


@router.delete("/sanction-operations/{operation_id}/members/{assistant_id}")
async def remove_operation_member(
    request: Request,
    operation_id: Snowflake,
    assistant_id: Snowflake,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    try:
        result = await db.remove_queued_batch_member(
            batch_id=operation_id,
            assistant_id=assistant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Операция выдачи не найдена")
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="sanction.operation.member.remove",
        target_type="sanction_operation",
        target_id=str(operation_id),
        details={
            "summary": f"Removed assistant {assistant_id} from sanction operation {operation_id}",
            "meta": {"trace_id": trace_id, "actor_id": _actor_id(principal)},
        },
    )
    return JSONResponse(
        content=success_envelope(
            data=_response_data(_operation_response(result)),
            message="Ассистент удален из операции",
            trace_id=trace_id,
        )
    )


@router.post("/sanction-operations/{operation_id}/issue-now")
async def issue_sanction_operation_now(
    request: Request,
    operation_id: Snowflake,
    db: "Database" = Depends(get_db),
    broker: "BrokerService | None" = Depends(get_broker),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    operation = await db.get_queued_sanction_batch(operation_id)
    if not operation:
        raise HTTPException(status_code=404, detail="Операция выдачи не найдена")
    if str(operation.get("status")) != "queued":
        raise HTTPException(
            status_code=409,
            detail="Операцию можно выдать сейчас только из очереди выдачи",
        )
    publish_result = await publish_integration_event(
        request.app,
        routing_key="sanction.operation.issue_now",
        payload={
            "event": "sanction.operation.issue_now",
            "operation_id": operation_id,
            "requested_by_id": _actor_id(principal),
            "trace_id": trace_id,
            "requested_at": datetime.now(MSK).isoformat(),
        },
    )
    if not publish_result:
        raise HTTPException(status_code=503, detail="Не удалось отправить задачу в worker")
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="sanction.operation.issue_now",
        target_type="sanction_operation",
        target_id=str(operation_id),
        details={
            "summary": f"Requested immediate issue for sanction operation {operation_id}",
            "meta": {"trace_id": trace_id, "actor_id": _actor_id(principal)},
        },
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=success_envelope(
            data=_response_data(_operation_response(operation)),
            message="Задача на немедленную выдачу отправлена в worker",
            code="SANCTION_OPERATION_ISSUE_NOW_REQUESTED",
            trace_id=trace_id,
        )
    )


@router.post("/sanction-operations/{operation_id}/cancel")
async def cancel_sanction_operation(
    request: Request,
    operation_id: Snowflake,
    db: "Database" = Depends(get_db),
    principal: dict = Depends(require_permission("assistants.sanctions.manage")),
):
    trace_id = get_trace_id(request)
    try:
        result = await db.cancel_queued_sanction_batch(operation_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Операция выдачи не найдена")
    await db.log_admin_action_v2(
        actor_name=_actor_name(principal),
        actor_role=principal.get("role"),
        action="sanction.operation.cancel",
        target_type="sanction_operation",
        target_id=str(operation_id),
        details={"summary": f"Cancelled sanction operation {operation_id}", "meta": {"trace_id": trace_id, "actor_id": _actor_id(principal)}},
    )
    return JSONResponse(
        content=success_envelope(
            data=_response_data(_operation_response(result)),
            message="Операция отменена",
            code="SANCTION_OPERATION_CANCELLED",
            trace_id=trace_id,
        )
    )
