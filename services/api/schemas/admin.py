from datetime import date

from pydantic import BaseModel

from schemas.common import Snowflake


class UserCreate(BaseModel):
    username: str
    nickname: str
    role: str
    discord_id: Snowflake
    appointed_at: date | None = None
