"""
Schemas for punishment returns workflow.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.common import Snowflake
from schemas.enums import PunishmentReturnStatus, PunishmentType, ReturnRemoveReason

MSK = timezone(timedelta(hours=3))


def make_aware(value: object) -> object:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=MSK)
    return value


class PunishmentReturnCreate(BaseModel):
    punishment_type: PunishmentType
    static: int = Field(..., ge=1)
    server: int = Field(..., ge=1, le=17)
    duration: int = Field(..., ge=1)
    remove_reason: ReturnRemoveReason
    discord_message_url: Optional[str] = Field(None, max_length=512)

    @field_validator("discord_message_url", mode="before")
    @classmethod
    def normalize_discord_message_url(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class PunishmentReturnUpdate(BaseModel):
    punishment_type: Optional[PunishmentType] = None
    static: Optional[int] = Field(None, ge=1)
    server: Optional[int] = Field(None, ge=1, le=17)
    duration: Optional[int] = Field(None, ge=1)
    remove_reason: Optional[ReturnRemoveReason] = None
    discord_message_url: Optional[str] = Field(None, max_length=512)

    @field_validator("discord_message_url", mode="before")
    @classmethod
    def normalize_discord_message_url(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class PunishmentReturnRecord(BaseModel):
    id: Snowflake
    punishment_type: PunishmentType
    static: int
    server: int
    duration: int
    remove_reason: ReturnRemoveReason
    discord_message_url: Optional[str] = None
    removed_by_id: Snowflake
    removed_by_name: str
    removed_at: datetime
    claimed_by_id: Optional[Snowflake] = None
    claimed_by_name: Optional[str] = None
    claimed_at: Optional[datetime] = None
    completed_by_id: Optional[Snowflake] = None
    completed_by_name: Optional[str] = None
    completed_at: Optional[datetime] = None
    status: PunishmentReturnStatus
    created_at: datetime
    updated_at: datetime
    status_label: Optional[str] = None
    remove_command: Optional[str] = None
    return_command: Optional[str] = None
    can_claim: bool = False
    can_complete: bool = False
    can_release: bool = False
    can_edit: bool = False
    can_delete: bool = False

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def apply_timezone(cls, data):
        if isinstance(data, dict):
            for field in [
                "removed_at",
                "claimed_at",
                "completed_at",
                "created_at",
                "updated_at",
            ]:
                if field in data and data[field]:
                    data[field] = make_aware(data[field])
        return data


class PunishmentReturnActionResponse(BaseModel):
    id: Snowflake
    status: PunishmentReturnStatus


class PunishmentReturnHistoryResponse(BaseModel):
    items: list[PunishmentReturnRecord]
    total: int
    page: int
    pages: int
