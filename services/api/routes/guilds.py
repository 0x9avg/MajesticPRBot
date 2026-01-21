"""
Guild settings routes for API.
Refactored to use database methods.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from schemas.guild import (
    GuildSettingsUpdate,
    GuildTemplatesUpdate,
    GuildRatesUpdate,
    GuildSettingsResponse,
)
from config import Config

router = APIRouter(prefix="/guild", tags=["Guild Settings"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


@router.get("", response_model=GuildSettingsResponse)
async def get_guild_settings(db=Depends(get_db)):
    """Get current guild settings."""
    settings = await db.get_guild(Config.GUILD_ID)
    
    if not settings:
        # Create default settings if not exist
        await db.create_or_update_guild(Config.GUILD_ID)
        settings = await db.get_guild(Config.GUILD_ID)
    
    return GuildSettingsResponse(**settings)


@router.patch("", response_model=GuildSettingsResponse)
async def update_guild_settings(
    data: GuildSettingsUpdate,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """Update guild channel settings."""
    # Update core settings
    await db.create_or_update_guild(
        Config.GUILD_ID,
        notification_channel_id=data.notification_channel_id,
        monitoring_channel_id=data.monitoring_channel_id,
        monitoring_message_id=data.monitoring_message_id,
    )
    
    # Update extended settings if provided
    if any([
        data.pr_actions_channel_id,
        data.control_panel_channel_id,
        data.control_panel_message_id,
        data.assistant_role_id,
    ]):
        await db.update_guild_extended_settings(
            Config.GUILD_ID,
            pr_actions_channel_id=data.pr_actions_channel_id,
            control_panel_channel_id=data.control_panel_channel_id,
            control_panel_message_id=data.control_panel_message_id,
            assistant_role_id=data.assistant_role_id,
        )
    
    settings = await db.get_guild(Config.GUILD_ID)
    
    if broker:
        await broker.emit_guild_settings_updated(Config.GUILD_ID, data.model_dump(exclude_none=True))
    
    return GuildSettingsResponse(**settings)


@router.patch("/templates", response_model=GuildSettingsResponse)
async def update_guild_templates(
    data: GuildTemplatesUpdate,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """Update notification templates."""
    await db.update_guild_templates(
        Config.GUILD_ID,
        template_stream_online=data.template_stream_online,
        template_stream_offline=data.template_stream_offline,
        template_category_to_gta=data.template_category_to_gta,
        template_category_from_gta=data.template_category_from_gta,
    )
    
    settings = await db.get_guild(Config.GUILD_ID)
    
    if broker:
        await broker.emit_guild_settings_updated(Config.GUILD_ID, {"templates": data.model_dump(exclude_none=True)})
    
    return GuildSettingsResponse(**settings)


@router.patch("/rates", response_model=GuildSettingsResponse)
async def update_guild_rates(
    data: GuildRatesUpdate,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """Update point rates per priority."""
    await db.update_guild_rates(
        Config.GUILD_ID,
        p0_rate=data.p0_rate,
        p1_rate=data.p1_rate,
        p2_rate=data.p2_rate,
        p3_rate=data.p3_rate,
    )
    
    settings = await db.get_guild(Config.GUILD_ID)
    
    if broker:
        await broker.emit_guild_settings_updated(Config.GUILD_ID, {"rates": data.model_dump(exclude_none=True)})
    
    return GuildSettingsResponse(**settings)


@router.get("/templates/{event_type}")
async def get_template(event_type: str, db=Depends(get_db)):
    """Get a specific notification template."""
    if event_type not in Config.ALLOWED_EVENT_TYPES:
        raise HTTPException(status_code=400, detail="Недопустимый тип события")
    
    template = await db.get_notification_template(Config.GUILD_ID, event_type)
    return {"event_type": event_type, "template": template}
