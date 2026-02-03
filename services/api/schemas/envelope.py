"""
API Response Envelope.
Standardized JSON envelope for all API responses.
"""

from enum import Enum
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseStatus(str, Enum):
    """Standard response status codes."""

    SUCCESS = "success"
    ACCEPTED = "accepted"
    ERROR = "error"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    VALIDATION_FAILED = "validation_failed"


class FieldError(BaseModel):
    """Validation error for a specific field."""

    field: str
    reason: str


class APIEnvelope(BaseModel, Generic[T]):
    """
    Standard API response envelope.
    All API endpoints should return responses wrapped in this envelope.
    """

    status: ResponseStatus = Field(
        ..., description="Response status code", examples=["success"]
    )
    code: Optional[str] = Field(
        None,
        description="Machine-readable code for specific scenarios",
        examples=["STREAMER_ADDED", "PROBATION_CHOICE_REQUIRED"],
    )
    message: str = Field(
        ..., description="Human-readable message", examples=["Streamer added"]
    )
    data: Optional[T] = Field(None, description="Response payload data")
    errors: Optional[List[FieldError]] = Field(
        None, description="Validation errors (if any)"
    )
    trace_id: Optional[str] = Field(
        None, description="Trace ID for request tracking", examples=["abc123"]
    )


# ============================================================================
# Helper functions to create envelopes
# ============================================================================


def success_envelope(
    data: Any = None,
    message: str = "OK",
    code: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> dict:
    """Create a success envelope."""
    return APIEnvelope(
        status=ResponseStatus.SUCCESS,
        code=code,
        message=message,
        data=data,
        trace_id=trace_id,
    ).model_dump(mode="json", exclude_none=True)


def accepted_envelope(
    data: Any = None,
    message: str = "Request accepted",
    code: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> dict:
    """Create an accepted envelope (for async operations)."""
    return APIEnvelope(
        status=ResponseStatus.ACCEPTED,
        code=code,
        message=message,
        data=data,
        trace_id=trace_id,
    ).model_dump(mode="json", exclude_none=True)


def error_envelope(
    message: str,
    code: Optional[str] = None,
    errors: Optional[List[FieldError]] = None,
    trace_id: Optional[str] = None,
) -> dict:
    """Create an error envelope."""
    return APIEnvelope(
        status=ResponseStatus.ERROR,
        code=code,
        message=message,
        errors=errors,
        trace_id=trace_id,
    ).model_dump(mode="json", exclude_none=True)


def conflict_envelope(
    message: str,
    code: Optional[str] = None,
    data: Any = None,
    trace_id: Optional[str] = None,
) -> dict:
    """Create a conflict envelope (409)."""
    return APIEnvelope(
        status=ResponseStatus.CONFLICT,
        code=code,
        message=message,
        data=data,
        trace_id=trace_id,
    ).model_dump(mode="json", exclude_none=True)


def not_found_envelope(
    message: str = "Resource not found",
    code: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> dict:
    """Create a not found envelope (404)."""
    return APIEnvelope(
        status=ResponseStatus.NOT_FOUND,
        code=code,
        message=message,
        trace_id=trace_id,
    ).model_dump(mode="json", exclude_none=True)


def validation_failed_envelope(
    message: str = "Validation failed",
    errors: Optional[List[FieldError]] = None,
    trace_id: Optional[str] = None,
) -> dict:
    """Create a validation failed envelope (422)."""
    return APIEnvelope(
        status=ResponseStatus.VALIDATION_FAILED,
        code="VALIDATION_FAILED",
        message=message,
        errors=errors,
        trace_id=trace_id,
    ).model_dump(mode="json", exclude_none=True)
