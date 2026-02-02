"""
Assistant schemas for API requests and responses.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from schemas.common import Snowflake


class AssistantBase(BaseModel):
    user_id: str = Field(..., description="Discord user ID")


class AssistantCreate(BaseModel):
    """Schema for creating/updating an assistant."""

    pr_id: int
    nickname: str
    role: (
        str  # 'junior_employee', 'employee', 'senior_employee', 'manager', 'developer'
    )
    experience_days: int = 0


class AssistantAssignment(BaseModel):
    """Schema for updating assistant assignment."""

    assigned_to_type: Optional[str] = None  # 'streamer', 'event', or None
    assigned_to_id: Optional[int] = None
    assigned_to_name: Optional[str] = None


class AssistantResponse(BaseModel):
    pr_id: Snowflake
    total_spec_seconds: int
    session_count: int
    added_at: datetime

    class Config:
        from_attributes = True


class AssistantStatsResponse(BaseModel):
    pr_id: Snowflake
    total_spec_seconds: int
    total_spec_formatted: str
    session_count: int
    daily_stats: List[dict] = []


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
    target_id: Optional[int] = None  # Streamer ID (optional)
    target_name: Optional[str] = None  # For display purposes
    target_type: str = "streamer"  # 'streamer' or 'event'
    duration_seconds: int
    date: str  # YYYY-MM-DD
    is_probation: bool = False
    priority: int = 0  # For points calculation
    admin_id: int  # Who created this session (for audit log)
