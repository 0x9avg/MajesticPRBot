from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from schemas.common import Snowflake


class EventBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: str = Field(..., max_length=1000)
    required_pr_count: int = Field(default=1, gt=0)
    start_time: Optional[datetime] = None
    channel_id: Optional[Snowflake] = None


class EventCreate(EventBase):
    created_by: Snowflake


class EventResponse(EventBase):
    id: int
    is_active: bool
    created_at: datetime
    created_by: Optional[Snowflake] = None
    message_id: Optional[Snowflake] = None
    notification_sent: bool
    current_participants: int = 0  # To be filled by query count


class EventJoinRequest(BaseModel):
    user_id: Snowflake


class EventEndResponse(BaseModel):
    status: str
    event_id: int
    participants: List[dict]
