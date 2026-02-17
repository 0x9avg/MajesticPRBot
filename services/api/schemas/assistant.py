"""
Assistant schemas for API requests and responses.
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.common import Snowflake


class AssistantBase(BaseModel):
    user_id: str = Field(..., description="Discord user ID")


class AssistantCreate(BaseModel):
    """Schema for creating/updating an assistant."""

    pr_id: Snowflake
    nickname: str
    role: (
        str  # 'junior_employee', 'employee', 'senior_employee', 'manager', 'developer'
    )
    experience_days: int = 0


class AssistantAssignment(BaseModel):
    """Schema for updating assistant assignment."""

    assigned_to_type: Optional[str] = None  # 'streamer', 'event', or None
    assigned_to_id: Optional[Snowflake] = None
    assigned_to_name: Optional[str] = None


class AssistantResponse(BaseModel):
    pr_id: Snowflake
    total_spec_seconds: int
    session_count: int
    added_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssistantStatsResponse(BaseModel):
    pr_id: Snowflake
    total_spec_seconds: int
    total_spec_formatted: str
    session_count: int
    daily_stats: List[dict] = []


class AssistantFull(BaseModel):
    """Complete assistant data from database."""

    pr_id: Snowflake
    nickname: Optional[str] = None
    role: str
    experience_days: Optional[int] = 0
    status: str
    assigned_to_type: Optional[str] = None
    assigned_to_id: Optional[Snowflake] = None
    total_spec_seconds: int = 0
    session_count: int = 0
    added_at: Optional[datetime] = None
    appointed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    assigned_to_name: Optional[str] = None
    total_spec_hours: float = 0.0
    total_spec_hours_30d: float = 0.0
    avg_spec_hours_per_day_30d: float = 0.0
    auto_points_total: float = 0.0
    manual_points_adjustment: float = 0.0
    total_points: float = 0.0
    penalty_points: float = 0.0
    penalty_percent: float = 0.0
    display_points: float = 0.0
    warnings_units: int = 0
    strict_warnings: int = 0
    oral_warnings: int = 0
    warnings_display: str = "0/2 0/2"

    model_config = ConfigDict(from_attributes=True)


class DailyStatsUpdate(BaseModel):
    """Schema for manual daily stats update by admin."""

    date: str  # YYYY-MM-DD
    p0_seconds: Optional[int] = None
    p1_seconds: Optional[int] = None
    p2_seconds: Optional[int] = None
    p3_seconds: Optional[int] = None
    probation_seconds: Optional[int] = None
    total_points: Optional[float] = None


class ManualSpecSession(BaseModel):
    """Schema for creating a manual spec session (admin feature)."""

    target_id: Optional[Snowflake] = None  # Streamer ID (optional)
    target_name: Optional[str] = None  # For display purposes
    target_type: Literal["streamer", "event", "manual"] = "streamer"
    started_at: datetime
    ended_at: datetime
    is_probation: bool = False
    priority: int = Field(0, ge=0, le=3)  # For points calculation
    session_admin_comment: Optional[str] = None

    @model_validator(mode="after")
    def validate_session(self):
        if self.ended_at <= self.started_at:
            raise ValueError("ended_at must be greater than started_at")
        if self.target_type == "manual":
            if self.target_id is not None:
                raise ValueError("target_id must be null for manual sessions")
            if not (self.session_admin_comment or "").strip():
                raise ValueError(
                    "session_admin_comment is required for manual sessions"
                )
        elif self.target_id is None:
            raise ValueError("target_id is required for streamer/event sessions")
        return self


class AssistantSavedResponse(BaseModel):
    pr_id: Snowflake
    nickname: str


class AssignmentUpdateResponse(BaseModel):
    pr_id: Snowflake
    status: str


class AssistantDeletedResponse(BaseModel):
    pr_id: Snowflake


class StatsResetResponse(BaseModel):
    pr_id: Snowflake
    nickname: Optional[str] = None


class DailyStatsResponse(BaseModel):
    pr_id: Snowflake
    date: str


class SessionCreatedResponse(BaseModel):
    pr_id: Snowflake
    started_at: datetime
    ended_at: datetime


class AssistantSessionRecord(BaseModel):
    id: int
    pr_id: Snowflake
    target_type: Optional[str] = None
    target_id: Optional[Snowflake] = None
    target_name: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    end_reason: Optional[str] = None
    is_probation: bool = False
    priority_auto: Optional[int] = None
    priority_override: Optional[int] = None
    rate_auto: Optional[float] = None
    rate_override: Optional[float] = None
    credited_points: float = 0.0
    session_admin_comment: Optional[str] = None
    deleted_at: Optional[datetime] = None
    delete_reason: Optional[str] = None


class AssistantPointsAdjustRequest(BaseModel):
    delta: float
    reason: Optional[str] = None
    source: Optional[str] = "manual_adjust"


class AssistantSanctionsUpdateRequest(BaseModel):
    penalty_points: Optional[float] = None
    penalty_percent: Optional[float] = None
    reason: Optional[str] = None


class AssistantWarningsUpdateRequest(BaseModel):
    oral_delta: int = 0
    strict_delta: int = 0
    reason: Optional[str] = None


class AssistantSessionPatchRequest(BaseModel):
    target_type: Optional[Literal["streamer", "event", "manual"]] = None
    target_id: Optional[Snowflake] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    priority_override: Optional[int] = Field(None, ge=0, le=3)
    rate_override: Optional[float] = Field(None, ge=0)
    session_admin_comment: Optional[str] = None
    reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_patch(self):
        has_started = self.started_at is not None
        has_ended = self.ended_at is not None
        if has_started != has_ended:
            raise ValueError("started_at and ended_at must be provided together")
        if has_started and has_ended and self.ended_at <= self.started_at:
            raise ValueError("ended_at must be greater than started_at")

        if self.target_type in ("streamer", "event") and self.target_id is None:
            raise ValueError("target_id is required when target_type is streamer/event")

        if self.target_type == "manual":
            if self.target_id is not None:
                raise ValueError("target_id must be null when target_type is manual")
            if self.session_admin_comment is not None and not self.session_admin_comment.strip():
                raise ValueError(
                    "session_admin_comment cannot be empty for manual sessions"
                )
        return self
