"""Schemas for punishment removals workflow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.common import Snowflake
from schemas.enums import PunishmentRemovalReason, PunishmentRemovalType, WorkflowStatus, WorkflowTargetStatus

MSK = timezone(timedelta(hours=3))


def make_aware(value: object) -> object:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=MSK)
    return value


def _normalize_optional_str(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class PunishmentRemovalCreate(BaseModel):
    punishment_type: PunishmentRemovalType = Field(
        ...,
        validation_alias=AliasChoices("punishment_type", "removal_type"),
    )
    static: int = Field(..., ge=1)
    server: int = Field(..., ge=1)
    reason: PunishmentRemovalReason
    message_link: Optional[str] = Field(None, max_length=512)
    target_status: WorkflowTargetStatus

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value

    @field_validator("message_link", mode="before")
    @classmethod
    def normalize_message_link(cls, value: object) -> object:
        return _normalize_optional_str(value)


class PunishmentRemovalUpdate(BaseModel):
    punishment_type: Optional[PunishmentRemovalType] = Field(
        None,
        validation_alias=AliasChoices("punishment_type", "removal_type"),
    )
    static: Optional[int] = Field(None, ge=1)
    server: Optional[int] = Field(None, ge=1)
    reason: Optional[PunishmentRemovalReason] = None
    message_link: Optional[str] = Field(None, max_length=512)
    target_status: Optional[WorkflowTargetStatus] = None

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value

    @field_validator("message_link", mode="before")
    @classmethod
    def normalize_message_link(cls, value: object) -> object:
        return _normalize_optional_str(value)

    @model_validator(mode="after")
    def reject_null_server(self) -> "PunishmentRemovalUpdate":
        if "server" in self.model_fields_set and self.server is None:
            raise ValueError("server cannot be null")
        return self


class PunishmentRemovalRecord(BaseModel):
    id: int
    assistant_id: Snowflake
    assistant_name: str
    created_by_id: Optional[Snowflake] = None
    created_by_name: Optional[str] = None
    reviewed_by_id: Optional[Snowflake] = None
    reviewed_by_name: Optional[str] = None
    issued_by_id: Optional[Snowflake] = None
    issued_by_name: Optional[str] = None
    punishment_type: PunishmentRemovalType
    static: int
    server: int
    reason: str
    message_link: Optional[str] = None
    status: WorkflowStatus
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    issued_at: Optional[datetime] = None
    status_date: Optional[datetime] = None
    status_label: Optional[str] = None
    command: Optional[str] = None
    can_edit: bool = False
    can_delete: bool = False
    can_issue: bool = False
    can_submit: bool = False

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def apply_timezone(cls, data):
        if isinstance(data, dict):
            for field in [
                "created_at",
                "reviewed_at",
                "issued_at",
                "status_date",
            ]:
                if field in data and data[field]:
                    data[field] = make_aware(data[field])
        return data


class PunishmentRemovalHistoryResponse(BaseModel):
    items: list[PunishmentRemovalRecord]
    total: int
    page: int
    pages: int
