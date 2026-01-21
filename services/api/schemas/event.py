from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

class EventBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: str = Field(..., max_length=1000)
    required_pr_count: int = Field(..., gt=0)
    start_time: Optional[datetime] = None
    channel_id: int

class EventCreate(EventBase):
    created_by: int
    guild_id: int

class EventResponse(EventBase):
    id: int
    is_active: bool
    created_at: datetime
    created_by: int
    message_id: Optional[int] = None
    notification_sent: bool
    current_participants: int = 0  # To be filled by query count

class EventParticipant(BaseModel):
    user_id: int
    joined_at: datetime

class EventJoinRequest(BaseModel):
    user_id: int

class EventEndResponse(BaseModel):
    status: str
    event_id: int
    participants: List[dict]
