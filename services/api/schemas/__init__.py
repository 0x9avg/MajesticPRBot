"""
Schemas package - Pydantic models for API requests and responses.
"""

# Auth
from schemas.auth import LoginRequest, TokenResponse, UserResponse

# Streamers
from schemas.streamer import (
    StreamerBase,
    StreamerCreate,
    StreamerUpdate,
    StreamerResponse,
    StreamerListResponse,
    StreamerEvent,
)

# Assistants
from schemas.assistant import (
    AssistantBase,
    AssistantCreate,
    AssistantResponse,
    AssistantStatsResponse,
)

# Guild
from schemas.guild import (
    GuildSettingsUpdate,
    GuildTemplatesUpdate,
    GuildRatesUpdate,
    GuildSettingsResponse,
    GuildEvent,
)

# Spec
from schemas.spec import (
    SpecClaimRequest,
    SpecUnclaimRequest,
    SpecTransferRequest,
    SpecSessionResponse,
    ActiveSpecResponse,
    SpecEvent,
)

# Monitoring
from schemas.monitoring import MonitoringRefreshRequest, DashboardStatusResponse

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
    "StreamerEvent",
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
    "GuildEvent",
    # Spec
    "SpecClaimRequest",
    "SpecUnclaimRequest",
    "SpecTransferRequest",
    "SpecSessionResponse",
    "ActiveSpecResponse",
    "SpecEvent",
    # Monitoring
    "MonitoringRefreshRequest",
    "DashboardStatusResponse",
]
