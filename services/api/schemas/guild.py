"""
Guild schemas for API requests and responses.
"""

import json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.common import Snowflake


def _parse_json_list(v: Any) -> Optional[list]:
    """Parse JSON string to list if needed."""
    if v is None:
        return None
    if isinstance(v, str):
        return json.loads(v)
    return v


class GameServerDto(BaseModel):
    id: int
    full_name: str
    short_name: str
    command_name: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GameServerWriteItem(BaseModel):
    id: int | None = Field(default=None, ge=1)
    full_name: str = Field(..., min_length=1, max_length=255)
    short_name: str = Field(..., min_length=1, max_length=32)
    command_name: str = Field(..., min_length=1, max_length=32)
    sort_order: int = 0
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)

    @field_validator("full_name", "short_name", "command_name", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value


class GameServersReplaceRequest(BaseModel):
    items: list[GameServerWriteItem]


class RolePermissionsSnapshotItem(BaseModel):
    role: str = Field(..., min_length=1, max_length=50)
    permissions: dict[str, bool] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class RolePermissionsReplaceRequest(BaseModel):
    items: list[RolePermissionsSnapshotItem]

    @model_validator(mode="after")
    def validate_unique_roles(self) -> "RolePermissionsReplaceRequest":
        roles = [item.role for item in self.items]
        if len(roles) != len(set(roles)):
            raise ValueError("Duplicate roles are not allowed")
        return self


class SiteMaintenanceUpdate(BaseModel):
    site_maintenance_enabled: bool


class SiteSettingsResponse(BaseModel):
    site_maintenance_enabled: bool
    permission_catalog: list[str]
    role_permissions: list[RolePermissionsSnapshotItem]

    model_config = ConfigDict(from_attributes=True)


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
