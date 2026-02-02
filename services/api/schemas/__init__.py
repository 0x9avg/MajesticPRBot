"""
Schemas package - Pydantic models for API requests and responses.
"""

# Auth
# Assistants
from schemas.assistant import (
    AssistantBase,
    AssistantCreate,
    AssistantResponse,
    AssistantStatsResponse,
)
from schemas.auth import LoginRequest, TokenResponse, UserResponse

# Guild
from schemas.guild import (
    GuildRatesUpdate,
    GuildSettingsResponse,
    GuildSettingsUpdate,
    GuildTemplatesUpdate,
)

# Monitoring
from schemas.monitoring import MonitoringRefreshResponse

# Spec
from schemas.spec import (
    ActiveSpecResponse,
    SpecClaimRequest,
    SpecSessionResponse,
    SpecTransferRequest,
    SpecUnclaimRequest,
)

# Streamers
from schemas.streamer import (
    StreamerBase,
    StreamerCreate,
    StreamerListResponse,
    StreamerResponse,
    StreamerUpdate,
)

__all__ = [
    # Auth
    "LoginRequest",
    "TokenResponse",
    "UserResponse",
    # Streamers
    "StreamerBase",
    "StreamerCreate",
    "StreamerUpdate",
    "StreamerResponse",
    "StreamerListResponse",
    # Assistants
    "AssistantBase",
    "AssistantCreate",
    "AssistantResponse",
    "AssistantStatsResponse",
    # Guild
    "GuildSettingsUpdate",
    "GuildTemplatesUpdate",
    "GuildRatesUpdate",
    "GuildSettingsResponse",
    # Spec
    "SpecClaimRequest",
    "SpecUnclaimRequest",
    "SpecTransferRequest",
    "SpecSessionResponse",
    "ActiveSpecResponse",
    # Monitoring
    "MonitoringRefreshResponse",
]
