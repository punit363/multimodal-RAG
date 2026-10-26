"""Privacy-conscious API request summaries."""

import json
import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from app.telemetry import observe_request, reset_trace, set_trace


logger = logging.getLogger("rag_access")


async def log_request(request: Request, call_next):
    """Correlate responses with route-template logs, excluding user content."""
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    trace_token = set_trace(request_id)
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        response = JSONResponse(status_code=500, content={"detail": "Internal server error."})
        logger.error("Unhandled API request: request_id=%s error_type=%s", request_id, type(exc).__name__)
        request.state.error_type = type(exc).__name__
    route = request.scope.get("route")
    route_name = getattr(route, "path", "unmatched")
    duration_ms = round((time.monotonic() - started) * 1000, 1)
    observe_request(route_name, response.status_code, duration_ms, request_id,
                    getattr(request.state, "error_type", None))
    logger.info(json.dumps({
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "route": route_name,
        "status": response.status_code,
        "duration_ms": duration_ms,
    }, separators=(",", ":")))
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Trace-ID"] = request_id
    response.headers["Server-Timing"] = f"app;dur={duration_ms}"
    reset_trace(trace_token)
    return response
