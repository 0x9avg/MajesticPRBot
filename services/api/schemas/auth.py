"""
Auth schemas for API requests and responses.
"""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    discord_id: int
    username: str
    nickname: str
    role: str
    require_password_change: bool
