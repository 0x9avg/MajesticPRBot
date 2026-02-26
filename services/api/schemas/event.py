from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from schemas.common import Snowflake


class EventBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: str = Field(..., max_length=1000)
    required_pr_count: int = Field(default=1, gt=0)
    priority: int = Field(default=0, ge=0, le=3, description="Priority level 0-3")
    pr_slots: int = Field(default=1, ge=1, description="Number of PR assistant slots")
    is_pinned: bool = Field(default=False, description="Whether event is pinned")
    start_time: Optional[datetime] = None
    channel_id: Optional[Snowflake] = None


class EventCreate(EventBase):
    created_by: Snowflake


class EventParticipant(BaseModel):
    pr_id: Snowflake
    nickname: str


class EventResponse(EventBase):
    id: Snowflake
    is_active: bool
    created_at: datetime
    created_by: Optional[Snowflake] = None
    message_id: Optional[Snowflake] = None
    notification_sent: bool
    current_participants: int = 0
    participants: List[EventParticipant] = [] 
    

class EventJoinRequest(BaseModel):
    user_id: Snowflake


class EventEndResponse(BaseModel):
    status: str
    event_id: Snowflake
    participants: List[dict]
