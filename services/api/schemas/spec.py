"""
Spec system schemas for API requests and responses.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SpecClaimRequest(BaseModel):
    streamer_id: int = Field(..., description="Twitch streamer ID to claim")
    pr_id: int = Field(..., description="Discord user ID of assistant")


class SpecUnclaimRequest(BaseModel):
    streamer_id: int = Field(..., description="Twitch streamer ID to unclaim")
    reason: str = Field(default="manual", description="Reason for unclaiming")


class SpecTransferRequest(BaseModel):
    streamer_id: int
    from_pr_id: int
    to_pr_id: int


class SpecSessionResponse(BaseModel):
    id: int
    pr_id: int
    streamer_id: int
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    end_reason: Optional[str] = None

    class Config:
        from_attributes = True


class ActiveSpecResponse(BaseModel):
    streamer_id: int
    streamer_name: str
    pr_id: int
    assigned_at: datetime
    duration_seconds: int


# Broker event

