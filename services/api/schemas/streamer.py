"""
Streamer schemas for API requests and responses.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class StreamerBase(BaseModel):
    twitch_id: int = Field(..., description="Twitch user ID")
    login: str = Field(..., description="Twitch username")
    priority: int = Field(default=0, ge=0, le=3, description="Priority level 0-3")
    is_paid: bool = Field(default=False, description="Whether streamer is paid")


class StreamerCreate(BaseModel):
    twitch_url: str = Field(..., description="Twitch channel URL or username")
    priority: int = Field(default=0, ge=0, le=3)
    is_paid: bool = Field(default=False)


class StreamerUpdate(BaseModel):
    priority: Optional[int] = Field(None, ge=0, le=3)
    is_paid: Optional[bool] = None


class StreamerResponse(BaseModel):
    streamer_id: int
    streamer_name: str
    is_online: bool
    started_at: Optional[datetime] = None
    priority: int
    is_paid: bool
    game_id: Optional[int] = None
    game_name: Optional[str] = None
    stream_title: Optional[str] = None
    stream_thumbnail_url: Optional[str] = None
    added_at: datetime
    added_by_id: Optional[int] = None
    assigned_pr_id: Optional[int] = None
    assigned_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class StreamerListResponse(BaseModel):
    total: int
    online_count: int
    gta_count: int
    streamers: List[StreamerResponse]


# Broker event
class StreamerEvent(BaseModel):
    """Event published when streamer data changes."""
    event_type: str  # "added", "removed", "updated", "status_changed"
    streamer_id: int
    streamer_name: str
    data: Optional[dict] = None
