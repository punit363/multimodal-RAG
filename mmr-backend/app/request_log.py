"""Privacy-conscious API request summaries."""

import json
import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse


logger = logging.getLogger("rag_access")


async def log_request(request: Request, call_next):
    """Correlate responses with route-template logs, excluding user content."""
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        response = JSONResponse(status_code=500, content={"detail": "Internal server error."})
        logger.error("Unhandled API request: request_id=%s error_type=%s", request_id, type(exc).__name__)
    route = request.scope.get("route")
    route_name = getattr(route, "path", "unmatched")
    logger.info(json.dumps({
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "route": route_name,
        "status": response.status_code,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }, separators=(",", ":")))
    response.headers["X-Request-ID"] = request_id
    return response
