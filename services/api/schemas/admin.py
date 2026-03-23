from datetime import date

from pydantic import BaseModel, model_validator

from schemas.common import Snowflake

from datetime import timezone, timedelta, datetime
MSK = timezone(timedelta(hours=3))

def make_aware(v):
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=MSK)
    return v


class UserCreate(BaseModel):
    username: str
    nickname: str
    role: str
    discord_id: Snowflake
    appointed_at: date | None = None


    
    @model_validator(mode="before")
    @classmethod
    def apply_timezone(cls, data):
        if isinstance(data, dict):
            for field in ['appointed_at']:
                if field in data and data[field] and isinstance(data[field], datetime):
                    data[field] = make_aware(data[field])
        return data


class UserRoleUpdate(BaseModel):
    role: str


class UserDeactivateRequest(BaseModel):
    reason: str | None = None
