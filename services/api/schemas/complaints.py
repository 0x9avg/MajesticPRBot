"""Schemas for complaints workflow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.common import Snowflake
from schemas.enums import ComplaintPunishmentType, ComplaintStatus, WorkflowTargetStatus

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


class ComplaintPunishmentInput(BaseModel):
    id: Optional[int] = None
    punishment_type: ComplaintPunishmentType
    static: int = Field(..., ge=1)
    duration: Optional[int] = Field(None, ge=1)
    reason: str = Field(..., min_length=1, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value

    @model_validator(mode="after")
    def validate_duration(self) -> "ComplaintPunishmentInput":
        if self.punishment_type == ComplaintPunishmentType.WARN:
            if self.duration is not None:
                raise ValueError("warn punishment cannot include duration")
            return self
        if self.duration is None:
            raise ValueError("duration is required for timed punishments")
        return self


class ComplaintCreate(BaseModel):
    server: int = Field(..., ge=1)
    complaint_link: Optional[str] = Field(None, max_length=512)
    media: str = Field(..., min_length=1, max_length=1024)
    incident_at: datetime
    target_status: WorkflowTargetStatus
    punishments: list[ComplaintPunishmentInput] = Field(..., min_length=1)

    @field_validator("complaint_link", "media", mode="before")
    @classmethod
    def normalize_strings(cls, value: object) -> object:
        return _normalize_optional_str(value)

    @field_validator("incident_at", mode="before")
    @classmethod
    def normalize_incident_at(cls, value: object) -> object:
        return make_aware(value)


class ComplaintUpdate(BaseModel):
    server: Optional[int] = Field(None, ge=1)
    complaint_link: Optional[str] = Field(None, max_length=512)
    media: Optional[str] = Field(None, min_length=1, max_length=1024)
    incident_at: Optional[datetime] = None
    target_status: Optional[WorkflowTargetStatus] = None
    punishments: Optional[list[ComplaintPunishmentInput]] = Field(None, min_length=1)

    @field_validator("complaint_link", "media", mode="before")
    @classmethod
    def normalize_strings(cls, value: object) -> object:
        return _normalize_optional_str(value)

    @field_validator("incident_at", mode="before")
    @classmethod
    def normalize_incident_at(cls, value: object) -> object:
        return make_aware(value)

    @model_validator(mode="after")
    def require_media_for_content_updates(self) -> "ComplaintUpdate":
        touched_fields = set(self.model_fields_set)
        if touched_fields and touched_fields <= {"target_status"}:
            return self

        content_fields = {"server", "complaint_link", "media", "incident_at", "punishments"}
        if any(field in touched_fields for field in content_fields) and self.media is None:
            raise ValueError("media is required for complaint updates")
        return self

    @model_validator(mode="after")
    def reject_null_server(self) -> "ComplaintUpdate":
        if "server" in self.model_fields_set and self.server is None:
            raise ValueError("server cannot be null")
        return self


class ComplaintPunishmentRecord(BaseModel):
    id: int
    complaint_id: int
    punishment_type: ComplaintPunishmentType
    static: int
    duration: Optional[int] = None
    reason: str
    command: Optional[str] = None
    message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ComplaintQueueItem(BaseModel):
    id: int
    complaint_id: int
    assistant_id: Snowflake
    assistant_name: str
    created_by_id: Optional[Snowflake] = None
    created_by_name: Optional[str] = None
    reviewed_by_id: Optional[Snowflake] = None
    reviewed_by_name: Optional[str] = None
    issued_by_id: Optional[Snowflake] = None
    issued_by_name: Optional[str] = None
    server: int
    complaint_link: Optional[str] = None
    media: Optional[str] = None
    incident_at: datetime
    status: ComplaintStatus
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    issued_at: Optional[datetime] = None
    status_date: Optional[datetime] = None
    status_label: Optional[str] = None
    command: Optional[str] = None
    message: Optional[str] = None
    aggregate_command: Optional[str] = None
    aggregate_message: Optional[str] = None
    punishments_count: int = 1
    punishments: list[ComplaintPunishmentRecord] = Field(default_factory=list)
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
                "incident_at",
                "created_at",
                "reviewed_at",
                "issued_at",
                "status_date",
            ]:
                if field in data and data[field]:
                    data[field] = make_aware(data[field])
        return data


class ComplaintDetailRecord(ComplaintQueueItem):
    pass


class ComplaintHistoryResponse(BaseModel):
    items: list[ComplaintQueueItem]
    total: int
    page: int
    pages: int
