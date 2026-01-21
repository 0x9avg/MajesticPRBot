"""
Assistant schemas for API requests and responses.
"""

from datetime import datetime
from typing import List
from pydantic import BaseModel, Field


class AssistantBase(BaseModel):
    user_id: int = Field(..., description="Discord user ID")


class AssistantCreate(AssistantBase):
    pass


class AssistantResponse(BaseModel):
    pr_id: int
    total_spec_seconds: int
    session_count: int
    added_at: datetime

    class Config:
        from_attributes = True


class AssistantStatsResponse(BaseModel):
    pr_id: int
    total_spec_seconds: int
    total_spec_formatted: str
    session_count: int
    daily_stats: List[dict] = []
