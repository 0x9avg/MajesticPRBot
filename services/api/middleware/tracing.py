"""
Tracing Middleware.
Handles trace_id generation and propagation for distributed tracing.
"""

import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

TRACE_ID_HEADER = "X-Trace-Id"


class TracingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle trace_id generation and propagation.

    - Extracts X-Trace-Id from incoming request headers (if present)
    - Generates a new trace_id if not present
    - Stores trace_id in request.state.trace_id
    - Adds X-Trace-Id to response headers
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract or generate trace_id
        trace_id = request.headers.get(TRACE_ID_HEADER)
        if not trace_id:
            trace_id = str(uuid.uuid4())

        # Store in request state for access by route handlers
        request.state.trace_id = trace_id

        # Process request
        response = await call_next(request)

        # Add trace_id to response headers
        response.headers[TRACE_ID_HEADER] = trace_id

        return response


def get_trace_id(request: Request) -> str:
    """
    Get trace_id from request state.
    Falls back to generating a new one if not present (should not happen with middleware).
    """
    return getattr(request.state, "trace_id", str(uuid.uuid4()))
