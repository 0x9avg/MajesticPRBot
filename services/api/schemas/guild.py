"""
Guild schemas for API requests and responses.
"""

from typing import Optional
from pydantic import BaseModel


class GuildSettingsUpdate(BaseModel):
    notification_channel_id: Optional[int] = None
    monitoring_channel_id: Optional[int] = None
    monitoring_message_id: Optional[int] = None
    pr_actions_channel_id: Optional[int] = None
    control_panel_channel_id: Optional[int] = None
    control_panel_message_id: Optional[int] = None
    assistant_role_id: Optional[int] = None


class GuildTemplatesUpdate(BaseModel):
    template_stream_online: Optional[str] = None
    template_stream_offline: Optional[str] = None
    template_category_to_gta: Optional[str] = None
    template_category_from_gta: Optional[str] = None


class GuildRatesUpdate(BaseModel):
    p0_rate: Optional[float] = None
    p1_rate: Optional[float] = None
    p2_rate: Optional[float] = None
    p3_rate: Optional[float] = None


class GuildSettingsResponse(BaseModel):
    guild_id: int
    notification_channel_id: Optional[int] = None
    monitoring_channel_id: Optional[int] = None
    monitoring_message_id: Optional[int] = None
    pr_actions_channel_id: Optional[int] = None
    control_panel_channel_id: Optional[int] = None
    control_panel_message_id: Optional[int] = None
    assistant_role_id: Optional[int] = None
    template_stream_online: Optional[str] = None
    template_stream_offline: Optional[str] = None
    template_category_to_gta: Optional[str] = None
    template_category_from_gta: Optional[str] = None
    p0_rate: Optional[float] = None
    p1_rate: Optional[float] = None
    p2_rate: Optional[float] = None
    p3_rate: Optional[float] = None

    class Config:
        from_attributes = True


# Broker event

