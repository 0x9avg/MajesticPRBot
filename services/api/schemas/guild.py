"""
Guild schemas for API requests and responses.
"""

from typing import Optional

from pydantic import BaseModel

from schemas.common import Snowflake


class GuildSettingsUpdate(BaseModel):
    notification_channel_id: Optional[Snowflake] = None
    monitoring_channel_id: Optional[Snowflake] = None
    monitoring_message_id: Optional[Snowflake] = None
    pr_actions_channel_id: Optional[Snowflake] = None
    control_panel_channel_id: Optional[Snowflake] = None
    control_panel_message_id: Optional[Snowflake] = None
    assistant_role_id: Optional[Snowflake] = None


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
    probation_rate: Optional[float] = None


class GuildSettingsResponse(BaseModel):
    """Full guild settings response (all fields)."""

    notification_channel_id: Optional[Snowflake] = None
    monitoring_channel_id: Optional[Snowflake] = None
    monitoring_message_id: Optional[Snowflake] = None
    pr_actions_channel_id: Optional[Snowflake] = None
    control_panel_channel_id: Optional[Snowflake] = None
    control_panel_message_id: Optional[Snowflake] = None
    assistant_role_id: Optional[Snowflake] = None
    template_stream_online: Optional[str] = None
    template_stream_offline: Optional[str] = None
    template_category_to_gta: Optional[str] = None
    template_category_from_gta: Optional[str] = None
    p0_rate: Optional[float] = None
    p1_rate: Optional[float] = None
    p2_rate: Optional[float] = None
    p3_rate: Optional[float] = None
    probation_rate: Optional[float] = None

    class Config:
        from_attributes = True


class GuildSettingsOnlyResponse(BaseModel):
    """Core wiring settings only (channel/role/message IDs)."""

    notification_channel_id: Optional[Snowflake] = None
    monitoring_channel_id: Optional[Snowflake] = None
    monitoring_message_id: Optional[Snowflake] = None
    pr_actions_channel_id: Optional[Snowflake] = None
    control_panel_channel_id: Optional[Snowflake] = None
    control_panel_message_id: Optional[Snowflake] = None
    assistant_role_id: Optional[Snowflake] = None

    class Config:
        from_attributes = True


class GuildTemplatesResponse(BaseModel):
    """Notification templates only."""

    template_stream_online: Optional[str] = None
    template_stream_offline: Optional[str] = None
    template_category_to_gta: Optional[str] = None
    template_category_from_gta: Optional[str] = None

    class Config:
        from_attributes = True


class GuildRatesResponse(BaseModel):
    """Point rates only."""

    p0_rate: Optional[float] = None
    p1_rate: Optional[float] = None
    p2_rate: Optional[float] = None
    p3_rate: Optional[float] = None
    probation_rate: Optional[float] = None

    class Config:
        from_attributes = True

