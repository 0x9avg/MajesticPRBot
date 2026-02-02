"""
Auth schemas for API requests and responses.
"""

from pydantic import BaseModel

from schemas.common import Snowflake


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    discord_id: Snowflake
    username: str
    nickname: str
    role: str
    require_password_change: bool
