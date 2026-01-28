"""
Streamer schemas for API requests and responses.
"""

import re
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from schemas.common import Snowflake


class StreamerBase(BaseModel):
    twitch_id: Snowflake = Field(..., description="Twitch user ID")
    login: str = Field(..., description="Twitch username")
    priority: int = Field(default=0, ge=0, le=3, description="Priority level 0-3")


class StreamerCreate(BaseModel):
    twitch_url: str = Field(..., description="Twitch channel URL or username")
    priority: int = Field(default=0, ge=0, le=3)
    
    @field_validator("twitch_url", mode="before")
    @classmethod
    def normalize_twitch_url(cls, v: str) -> str:
        """
        Normalize Twitch URL/username to clean username.
        
        Handles:
        - https://www.twitch.tv/username
        - https://twitch.tv/username
        - twitch.tv/username  
        - www.twitch.tv/username
        - username
        """
        if not v:
            raise ValueError("Twitch URL/username cannot be empty")
        
        v = v.strip()
        
        # Remove protocol
        v = re.sub(r'^https?://', '', v)
        
        # Remove www.
        v = re.sub(r'^www\.', '', v)
        
        # Remove twitch.tv/
        v = re.sub(r'^twitch\.tv/', '', v, flags=re.IGNORECASE)
        
        # Remove trailing slashes and query params
        v = v.split('?')[0].split('/')[0].strip()
        
        if not v:
            raise ValueError("Could not extract username from Twitch URL")
        
        # Basic validation: Twitch usernames are 4-25 chars, alphanumeric + underscore
        if not re.match(r'^[a-zA-Z0-9_]{1,25}$', v):
            raise ValueError(f"Invalid Twitch username: {v}")
        
        return v.lower()


class StreamerUpdate(BaseModel):
    priority: Optional[int] = Field(None, ge=0, le=3)


class StreamerResponse(BaseModel):
    streamer_id: Snowflake
    streamer_name: str
    is_online: bool
    started_at: Optional[datetime] = None
    priority: int
    game_id: Optional[Snowflake] = None
    game_name: Optional[str] = None
    stream_title: Optional[str] = None
    stream_thumbnail_url: Optional[str] = None
    added_at: datetime
    added_by_id: Optional[Snowflake] = None
    assigned_pr_id: Optional[Snowflake] = None
    assigned_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class StreamerListResponse(BaseModel):
    total: int
    online_count: int
    gta_count: int
    streamers: List[StreamerResponse]


# Broker event
