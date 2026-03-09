"""
Guild schemas for API requests and responses.
"""

import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from schemas.common import Snowflake


def _parse_json_list(v: Any) -> Optional[list]:
    """Parse JSON string to list if needed."""
    if v is None:
        return None
    if isinstance(v, str):
        return json.loads(v)
    return v


class GuildSettingsUpdate(BaseModel):
    notification_channel_id: Optional[Snowflake] = None
    monitoring_channel_id: Optional[Snowflake] = None
    monitoring_message_id: Optional[int] = None
    monitoring_filter_gta: Optional[bool] = None
    pr_actions_channel_id: Optional[Snowflake] = None
    control_panel_channel_id: Optional[Snowflake] = None
    control_panel_message_id: Optional[Snowflake] = None


class GuildTemplatesUpdate(BaseModel):
    stream_online_gta: Optional[str] = None
    stream_online_other: Optional[str] = None
    stream_offline: Optional[str] = None
    category_to_gta: Optional[str] = None
    category_from_gta: Optional[str] = None


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
    monitoring_message_id: Optional[int] = None
    monitoring_filter_gta: Optional[bool] = None
    pr_actions_channel_id: Optional[Snowflake] = None
    control_panel_channel_id: Optional[Snowflake] = None
    control_panel_message_id: Optional[Snowflake] = None
    template_stream_online_gta: Optional[str] = None
    template_stream_online_other: Optional[str] = None
    template_stream_offline: Optional[str] = None
    template_category_to_gta: Optional[str] = None
    template_category_from_gta: Optional[str] = None
    p0_rate: Optional[float] = None
    p1_rate: Optional[float] = None
    p2_rate: Optional[float] = None
    p3_rate: Optional[float] = None
    probation_rate: Optional[float] = None



    model_config = ConfigDict(from_attributes=True)


class GuildSettingsOnlyResponse(BaseModel):
    """Core wiring settings only (channel/role/message IDs)."""

    notification_channel_id: Optional[Snowflake] = None
    monitoring_channel_id: Optional[Snowflake] = None
    monitoring_message_id: Optional[int] = None
    monitoring_filter_gta: Optional[bool] = None
    pr_actions_channel_id: Optional[Snowflake] = None
    control_panel_channel_id: Optional[Snowflake] = None
    control_panel_message_id: Optional[Snowflake] = None



    model_config = ConfigDict(from_attributes=True)


class GuildTemplatesResponse(BaseModel):
    """Notification templates only."""

    stream_online_gta: Optional[str] = None
    stream_online_other: Optional[str] = None
    stream_offline: Optional[str] = None
    category_to_gta: Optional[str] = None
    category_from_gta: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class GuildRatesResponse(BaseModel):
    """Point rates only."""

    p0_rate: Optional[float] = None
    p1_rate: Optional[float] = None
    p2_rate: Optional[float] = None
    p3_rate: Optional[float] = None
    probation_rate: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)
