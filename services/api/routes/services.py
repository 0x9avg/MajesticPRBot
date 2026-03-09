from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from database import Database
    from services.broker import BrokerService

from dependencies import get_current_service, require_permission
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from pydantic import BaseModel, Field
from runtime_status import (
    get_api_runtime_status,
    get_service_registry_view,
    record_service_heartbeat,
)
from schemas.envelope import accepted_envelope, error_envelope, success_envelope

router = APIRouter(prefix="/services", tags=["Services"])


def get_db(request: Request):
    return request.app.state.database


def get_broker(request: Request):
    return request.app.state.broker


class ServiceHeartbeatRequest(BaseModel):
    status: str = Field(..., description="Current runtime status of the service")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary structured runtime details",
    )


@router.post("/heartbeat")
async def report_service_heartbeat(
    request: Request,
    payload: ServiceHeartbeatRequest,
    principal: dict = Depends(get_current_service),
):
    trace_id = get_trace_id(request)
    service_name = str(principal.get("service_name") or "unknown_service")
    snapshot = record_service_heartbeat(
        request.app,
        service_name,
        status=payload.status,
        details=payload.details,
    )

    return JSONResponse(
        content=success_envelope(
            data={
                "service_name": service_name,
                "status": snapshot["status"],
            },
            message="Service heartbeat stored",
            code="SERVICE_HEARTBEAT_STORED",
            trace_id=trace_id,
        )
    )


@router.get("/overview")
async def get_services_overview(
    request: Request,
    db: "Database" = Depends(get_db),
    _principal: dict = Depends(require_permission("monitoring.view")),
):
    trace_id = get_trace_id(request)
    api_status = await get_api_runtime_status(request.app)
    domain_stats = await db.get_service_overview_stats()
    services = get_service_registry_view(request.app)

    return JSONResponse(
        content=success_envelope(
            data={
                "generated_at": api_status["checked_at"],
                "api": api_status,
                "services": services,
                "domain": domain_stats,
            },
            message="Service overview retrieved",
            code="SERVICE_OVERVIEW_RETRIEVED",
            trace_id=trace_id,
        )
    )


@router.post("/twitch/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_twitch_sync(
    request: Request,
    broker: "BrokerService" = Depends(get_broker),
    principal: dict = Depends(require_permission("streamers.status.update")),
):
    trace_id = get_trace_id(request)

    if not broker:
        return JSONResponse(
            status_code=503,
            content=error_envelope(
                message="Broker unavailable",
                code="BROKER_UNAVAILABLE",
                trace_id=trace_id,
            ),
        )

    await broker.publish(
        "service.twitch.sync",
        {
            "event": "service.twitch.sync",
            "trace_id": trace_id,
            "requested_by": {
                "principal_type": principal.get("principal_type"),
                "service_name": principal.get("service_name"),
                "username": principal.get("username"),
                "nickname": principal.get("nickname"),
            },
        },
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=accepted_envelope(
            data={"trace_id": trace_id},
            message="Twitch sync requested",
            code="TWITCH_SYNC_REQUESTED",
            trace_id=trace_id,
        ),
    )
