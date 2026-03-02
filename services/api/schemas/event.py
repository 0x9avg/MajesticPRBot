from datetime import datetime, timezone, timedelta
from typing import List, Optional

# Moscow timezone (UTC+3)
MSK = timezone(timedelta(hours=3))

from pydantic import BaseModel, Field, field_validator

from schemas.common import Snowflake


class EventBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: str = Field(..., max_length=1000)
    required_pr_count: int = Field(default=1, gt=0)
    priority: int = Field(default=0, ge=0, le=3, description="Priority level 0-3")
    pr_slots: int = Field(default=1, ge=1, description="Number of PR assistant slots")
    is_pinned: bool = Field(default=False, description="Whether event is pinned")
    start_time: Optional[datetime] = None

    @field_validator("start_time", mode="before")
    @classmethod
    def make_aware(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=MSK)
        return v


class EventCreate(EventBase):
    created_by: Snowflake


class EventParticipant(BaseModel):
    pr_id: Snowflake
    nickname: Optional[str] = None
    status: Optional[str] = None


class EventResponse(EventBase):
    id: Snowflake
    is_active: bool
    created_at: datetime
    created_by: Optional[Snowflake] = None
    notification_sent: bool
    current_participants: int = 0
    participants: List[EventParticipant] = []
    event_kind: Optional[str] = "regular"
    approval_status: Optional[str] = "approved"
    requested_by: Optional[Snowflake] = None
    approved_by: Optional[Snowflake] = None
    approved_at: Optional[datetime] = None
    rejected_by: Optional[Snowflake] = None
    rejected_at: Optional[datetime] = None
    
    @field_validator("created_at", "approved_at", "rejected_at", mode="before")
    @classmethod
    def make_created_at_aware(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=MSK)
        return v
    

class EventJoinRequest(BaseModel):
    user_id: Snowflake


class EventEndResponse(BaseModel):
    status: str
    event_id: Snowflake
    participants: List[dict]


class SpecRequestCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: str = Field("", max_length=1000)
    priority: int = Field(default=0, ge=0, le=3)


class SpecRequestUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    priority: Optional[int] = Field(None, ge=0, le=3)
    start_time: Optional[datetime] = Field(None, description="Session start time override")
    end_time: Optional[datetime] = Field(None, description="Session end time override")

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def make_aware(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=MSK)
        return v
