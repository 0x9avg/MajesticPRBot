"""
Schemas package - Pydantic models for API requests and responses.
"""

# Envelope (API response wrapper)
# Auth
# Assistants
from schemas.assistant import (
    AssistantBase,
    AssistantCreate,
    AssistantResponse,
    AssistantStatsResponse,
)
from schemas.auth import LoginRequest, TokenResponse, UserResponse
from schemas.envelope import (
    APIEnvelope,
    FieldError,
    ResponseStatus,
    accepted_envelope,
    conflict_envelope,
    error_envelope,
    not_found_envelope,
    success_envelope,
    validation_failed_envelope,
)

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
    # Envelope
    "APIEnvelope",
    "FieldError",
    "ResponseStatus",
    "success_envelope",
    "accepted_envelope",
    "error_envelope",
    "conflict_envelope",
    "not_found_envelope",
    "validation_failed_envelope",
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
