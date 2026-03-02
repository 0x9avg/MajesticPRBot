"""
Spec system schemas for API requests and responses.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.common import Snowflake
from schemas.enums import SpecSessionEndReason

from datetime import timezone, timedelta
MSK = timezone(timedelta(hours=3))

def make_aware(v):
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=MSK)
    return v


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
    reason: str = Field(default=SpecSessionEndReason.MANUAL_UNCLAIM.value, description="Reason for unclaiming")





class SpecSessionResponse(BaseModel):
    id: Snowflake
    pr_id: Snowflake
    streamer_id: Snowflake
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    end_reason: Optional[SpecSessionEndReason] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def apply_timezone(cls, data):
        if isinstance(data, dict):
            for field in ['started_at', 'ended_at']:
                if field in data and data[field]:
                    data[field] = make_aware(data[field])
        return data


class ActiveSpecResponse(BaseModel):
    streamer_id: Snowflake
    streamer_name: str
    pr_id: Snowflake
    assigned_at: datetime
    duration_seconds: int

    @model_validator(mode="before")
    @classmethod
    def apply_timezone(cls, data):
        if isinstance(data, dict):
            for field in ['assigned_at']:
                if field in data and data[field]:
                    data[field] = make_aware(data[field])
        return data


# Broker event
