"""
Streamer schemas for API requests and responses.
"""

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from schemas.common import Snowflake


class StreamerBase(BaseModel):
    twitch_id: Snowflake = Field(..., description="Twitch user ID")
    login: str = Field(..., description="Twitch username")
    priority: int = Field(default=0, ge=0, le=3, description="Priority level 0-3")


class StreamerCreate(BaseModel):
    """
    Unified schema for creating a streamer.

    Two modes:
    1. URL mode (Discord/Web): Provide `twitch_url`, API will verify via broker
    2. Full mode (Twitch bot): Provide `streamer_id` + `streamer_name` + optional stream data
    """

    # Mode A: URL-based (needs resolution)
    twitch_url: Optional[str] = Field(
        None, description="Twitch channel URL or username"
    )

    # Mode B: Full data (Twitch bot already has resolved data)
    streamer_id: Optional[int] = Field(
        None, description="Twitch user ID (for direct creation)"
    )
    streamer_name: Optional[str] = Field(
        None, description="Twitch username (for direct creation)"
    )
    is_online: bool = Field(default=False)
    started_at: Optional[str] = None
    game_id: Optional[int] = None
    game_name: Optional[str] = None
    stream_title: Optional[str] = None
    stream_thumbnail_url: Optional[str] = None
    profile_image_url: Optional[str] = None

    # Common fields
    priority: int = Field(default=0, ge=0, le=3)
    added_by_id: int = Field(default=0)

    @field_validator("twitch_url", mode="before")
    @classmethod
    def normalize_twitch_url(cls, v: Optional[str]) -> Optional[str]:
        """Normalize Twitch URL/username to clean username."""
        if v is None:
            return None

        v = v.strip()
        if not v:
            return None

        # Remove protocol
        v = re.sub(r"^https?://", "", v)
        # Remove www.
        v = re.sub(r"^www\.", "", v)
        # Remove twitch.tv/
        v = re.sub(r"^twitch\.tv/", "", v, flags=re.IGNORECASE)
        # Remove trailing slashes and query params
        v = v.split("?")[0].split("/")[0].strip()

        if not v:
            return None

        # Basic validation: Twitch usernames are 4-25 chars, alphanumeric + underscore
        if not re.match(r"^[a-zA-Z0-9_]{1,25}$", v):
            raise ValueError(f"Invalid Twitch username: {v}")

        return v.lower()

    @model_validator(mode="after")
    def validate_input_mode(self):
        """Ensure either twitch_url OR (streamer_id + streamer_name) is provided."""
        has_url = self.twitch_url is not None
        has_full = self.streamer_id is not None and self.streamer_name is not None

        if not has_url and not has_full:
            raise ValueError(
                "Provide either 'twitch_url' OR ('streamer_id' + 'streamer_name')"
            )

        if has_url and has_full:
            # If both provided, prefer full data (more complete)
            pass

        return self

    @property
    def is_full_mode(self) -> bool:
        """Check if this request contains full data (Twitch bot mode)."""
        return self.streamer_id is not None and self.streamer_name is not None


class StreamerUpdate(BaseModel):
    priority: Optional[int] = Field(None, ge=0, le=3)
    is_pinned: Optional[bool] = None
    stream_points_override: Optional[float] = None


class StreamerResponse(BaseModel):
    streamer_id: Snowflake
    streamer_name: str
    is_online: bool
    is_pinned: bool = False
    stream_points_override: Optional[float] = None
    started_at: Optional[datetime] = None
    priority: int
    game_id: Optional[Snowflake] = None
    game_name: Optional[str] = None
    stream_title: Optional[str] = None
    stream_thumbnail_url: Optional[str] = None
    profile_image_url: Optional[str] = None
    added_at: datetime
    added_by_id: Optional[Snowflake] = None
    assignments: List[dict] = Field(default_factory=list)

    class Config:
        from_attributes = True


class StreamerListResponse(BaseModel):
    total: int
    online_count: int
    gta_count: int
    streamers: List[StreamerResponse]


# Broker event


# Schemas below kept for backward compatibility during transition


class StreamerStatusUpdate(BaseModel):
    """Schema for updating streamer status (Twitch bot)."""

    is_online: bool
    started_at: Optional[str] = None
    game_id: Optional[int] = None
    game_name: Optional[str] = None
    stream_title: Optional[str] = None
    stream_thumbnail_url: Optional[str] = None
    profile_image_url: Optional[str] = None
