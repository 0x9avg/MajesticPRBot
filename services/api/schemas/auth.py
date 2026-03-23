"""
Auth schemas for API requests and responses.
"""

from pydantic import BaseModel

from schemas.common import Snowflake


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response — only access_token in body, refresh in HttpOnly cookie."""
    access_token: str
    token_type: str = "bearer"


# Legacy alias for backward compatibility with imports
TokenResponse = LoginResponse


class UserResponse(BaseModel):
    id: Snowflake
    discord_id: Snowflake
    username: str
    nickname: str
    role: str
    require_password_change: bool
    permissions: dict[str, bool] = {}
    manageable_roles: list[str] = []
