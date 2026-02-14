"""
Exception Handlers.
Global exception handlers that return standardized envelope responses.
"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from schemas.envelope import (
    FieldError,
    error_envelope,
    not_found_envelope,
    validation_failed_envelope,
)

logger = logging.getLogger("API")


def get_trace_id_safe(request: Request) -> str:
    """Safely get trace_id from request state."""
    return getattr(request.state, "trace_id", None)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Handle HTTPException and return envelope response.
    """
    trace_id = get_trace_id_safe(request)

    if exc.status_code == 404:
        content = not_found_envelope(message=str(exc.detail), trace_id=trace_id)
    else:
        content = error_envelope(message=str(exc.detail), trace_id=trace_id)

    return JSONResponse(status_code=exc.status_code, content=content)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handle RequestValidationError and return envelope response.
    """
    trace_id = get_trace_id_safe(request)

    # Convert Pydantic errors to FieldError list
    errors = []
    for error in exc.errors():
        loc = error.get("loc", [])
        # Join location parts (e.g., ["body", "username"] -> "body.username")
        field = ".".join(str(part) for part in loc)
        reason = error.get("msg", "Invalid value")
        errors.append(FieldError(field=field, reason=reason))

    content = validation_failed_envelope(
        message="Validation failed", errors=errors, trace_id=trace_id
    )

    return JSONResponse(status_code=422, content=content)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle uncaught exceptions and return envelope response.
    """
    trace_id = get_trace_id_safe(request)

    logger.error(f"Unhandled exception [trace_id={trace_id}]: {exc}", exc_info=True)

    content = error_envelope(
        message="Internal server error",
        code="INTERNAL_ERROR",
        trace_id=trace_id,
    )

    return JSONResponse(status_code=500, content=content)


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers on the FastAPI app.
    """
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
