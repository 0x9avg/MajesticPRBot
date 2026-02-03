"""
Spec system schemas for API requests and responses.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from schemas.common import Snowflake


class SpecClaimRequest(BaseModel):
    streamer_id: Snowflake = Field(..., description="Twitch streamer ID to claim")
    pr_id: Snowflake = Field(..., description="Discord user ID of assistant")
    is_probation: bool = Field(
        default=False, description="Whether this is a probation (trainee) claim"
    )


class SpecUnclaimRequest(BaseModel):
    streamer_id: Snowflake = Field(..., description="Twitch streamer ID to unclaim")
    pr_id: Optional[Snowflake] = Field(
        None, description="Discrod user ID of assistant (optional)"
    )
    reason: str = Field(default="manual", description="Reason for unclaiming")


class SpecTransferRequest(BaseModel):
    streamer_id: Snowflake
    from_pr_id: Snowflake
    to_pr_id: Snowflake


class SpecSwapRequest(BaseModel):
    """Request to swap streamers between two PRs."""

    pr1_id: Snowflake = Field(..., description="First PR assistant ID")
    pr2_id: Snowflake = Field(..., description="Second PR assistant ID")


class SpecSessionResponse(BaseModel):
    id: int
    pr_id: Snowflake
    streamer_id: Snowflake
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    end_reason: Optional[str] = None

    class Config:
        from_attributes = True


class ActiveSpecResponse(BaseModel):
    streamer_id: Snowflake
    streamer_name: str
    pr_id: Snowflake
    assigned_at: datetime
    duration_seconds: int


# Broker event
