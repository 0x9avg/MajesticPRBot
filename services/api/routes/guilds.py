"""
Guild settings routes for API.
Split into /settings, /templates, /rates resources per roadmap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database
    from services.broker import BrokerService

from config import Config
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import success_envelope
from schemas.guild import (
    GuildRatesResponse,
    GuildRatesUpdate,
    GuildSettingsOnlyResponse,
    GuildSettingsResponse,
    GuildSettingsUpdate,
    GuildTemplatesResponse,
    GuildTemplatesUpdate,
)

router = APIRouter(prefix="/guild", tags=["Guild Settings"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


# =============================================================================
# Full Guild (backward compatibility / aggregated view)
# =============================================================================


@router.get("")
async def get_guild_all(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """Get all guild settings (aggregated view)."""
    trace_id = get_trace_id(request)

    settings = await db.get_guild()

    if not settings:
        await db.create_or_update_guild()
        settings = await db.get_guild()

    data = GuildSettingsResponse(**settings)
    return JSONResponse(
        content=success_envelope(
            data=data.model_dump(mode="json"),
            message="Guild settings retrieved",
            trace_id=trace_id,
        )
    )


# =============================================================================
# /settings - Core wiring (channel/role/message IDs)
# =============================================================================


@router.get("/settings")
async def get_guild_settings(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """Get core wiring settings (channel/role/message IDs)."""
    trace_id = get_trace_id(request)

    settings = await db.get_guild()

    if not settings:
        await db.create_or_update_guild()
        settings = await db.get_guild()

    data = GuildSettingsOnlyResponse(**settings)
    return JSONResponse(
        content=success_envelope(
            data=data.model_dump(mode="json"),
            message="Guild settings retrieved",
            trace_id=trace_id,
        )
    )


@router.patch("/settings")
async def update_guild_settings(
    request: Request,
    data: GuildSettingsUpdate,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
):
    """Update core wiring settings."""
    trace_id = get_trace_id(request)

    await db.create_or_update_guild(
        notification_channel_id=data.notification_channel_id,
        monitoring_channel_id=data.monitoring_channel_id,
        monitoring_message_ids=data.monitoring_message_ids,
        monitoring_filter_gta=data.monitoring_filter_gta,
        pr_actions_channel_id=data.pr_actions_channel_id,
        control_panel_channel_id=data.control_panel_channel_id,
        control_panel_message_id=data.control_panel_message_id,
    )

    settings = await db.get_guild()

    if broker:
        await broker.emit_guild_settings_updated(
            data.model_dump(exclude_none=True),
            trace_id=trace_id,
        )

    response_data = GuildSettingsOnlyResponse(**settings)
    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message="Guild settings updated",
            code="GUILD_SETTINGS_UPDATED",
            trace_id=trace_id,
        )
    )


# =============================================================================
# /templates - Notification templates
# =============================================================================


@router.get("/templates")
async def get_guild_templates(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """Get notification templates."""
    trace_id = get_trace_id(request)

    settings = await db.get_guild()

    if not settings:
        await db.create_or_update_guild()
        settings = await db.get_guild()

    # Parse notification_templates JSON and map to schema fields
    raw_templates = settings.get("notification_templates") if settings else None
    templates_dict = {}

    if isinstance(raw_templates, str):
        import json

        try:
            templates_dict = json.loads(raw_templates)
        except json.JSONDecodeError:
            templates_dict = {}
    elif isinstance(raw_templates, dict):
        templates_dict = raw_templates

    # Map DB keys to schema keys, using defaults for missing
    data = GuildTemplatesResponse(
        stream_online=templates_dict.get(
            "stream_online", Config.template_defaults.get("stream_online")
        ),
        stream_offline=templates_dict.get(
            "stream_offline", Config.template_defaults.get("stream_offline")
        ),
        category_to_gta=templates_dict.get(
            "category_to_gta", Config.template_defaults.get("category_to_gta")
        ),
        category_from_gta=templates_dict.get(
            "category_from_gta", Config.template_defaults.get("category_from_gta")
        ),
    )
    return JSONResponse(
        content=success_envelope(
            data=data.model_dump(mode="json"),
            message="Guild templates retrieved",
            trace_id=trace_id,
        )
    )


@router.patch("/templates")
async def update_guild_templates(
    request: Request,
    data: GuildTemplatesUpdate,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
):
    """Update notification templates."""
    trace_id = get_trace_id(request)

    await db.update_guild_templates(
        template_stream_online=data.stream_online,
        template_stream_offline=data.stream_offline,
        template_category_to_gta=data.category_to_gta,
        template_category_from_gta=data.category_from_gta,
    )

    settings = await db.get_guild()

    if broker:
        await broker.emit_guild_templates_updated(
            data.model_dump(exclude_none=True),
            trace_id=trace_id,
        )

    # Parse notification_templates JSON and map to schema fields
    raw_templates = settings.get("notification_templates") if settings else None
    templates_dict = {}

    if isinstance(raw_templates, str):
        import json

        try:
            templates_dict = json.loads(raw_templates)
        except json.JSONDecodeError:
            templates_dict = {}
    elif isinstance(raw_templates, dict):
        templates_dict = raw_templates

    # Map DB keys to schema keys, using defaults for missing
    response_data = GuildTemplatesResponse(
        stream_online=templates_dict.get(
            "stream_online", Config.template_defaults.get("stream_online")
        ),
        stream_offline=templates_dict.get(
            "stream_offline", Config.template_defaults.get("stream_offline")
        ),
        category_to_gta=templates_dict.get(
            "category_to_gta", Config.template_defaults.get("category_to_gta")
        ),
        category_from_gta=templates_dict.get(
            "category_from_gta", Config.template_defaults.get("category_from_gta")
        ),
    )
    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message="Guild templates updated",
            code="GUILD_TEMPLATES_UPDATED",
            trace_id=trace_id,
        )
    )


@router.get("/templates/{event_type}")
async def get_template_by_type(
    request: Request,
    event_type: str,
    db: "Database" = Depends(get_db),
):
    """Get a specific notification template by event type."""
    trace_id = get_trace_id(request)

    if event_type not in Config.allowed_event_types:
        raise HTTPException(status_code=400, detail="Недопустимый тип события")

    template = await db.get_notification_template(event_type)
    return JSONResponse(
        content=success_envelope(
            data={"event_type": event_type, "template": template},
            message=f"Template for {event_type}",
            trace_id=trace_id,
        )
    )


# =============================================================================
# /rates - Point rates
# =============================================================================


@router.get("/rates")
async def get_guild_rates(
    request: Request,
    db: "Database" = Depends(get_db),
):
    """Get point rates per priority."""
    trace_id = get_trace_id(request)

    settings = await db.get_guild()

    if not settings:
        await db.create_or_update_guild()
        settings = await db.get_guild()

    data = GuildRatesResponse(**settings)
    return JSONResponse(
        content=success_envelope(
            data=data.model_dump(mode="json"),
            message="Guild rates retrieved",
            trace_id=trace_id,
        )
    )


@router.patch("/rates")
async def update_guild_rates(
    request: Request,
    data: GuildRatesUpdate,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
):
    """Update point rates per priority."""
    trace_id = get_trace_id(request)

    await db.update_guild_rates(
        p0_rate=data.p0_rate,
        p1_rate=data.p1_rate,
        p2_rate=data.p2_rate,
        p3_rate=data.p3_rate,
        probation_rate=data.probation_rate,
    )

    settings = await db.get_guild()

    if broker:
        await broker.emit_guild_rates_updated(
            data.model_dump(exclude_none=True),
            trace_id=trace_id,
        )

    response_data = GuildRatesResponse(**settings)
    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message="Guild rates updated",
            code="GUILD_RATES_UPDATED",
            trace_id=trace_id,
        )
    )
