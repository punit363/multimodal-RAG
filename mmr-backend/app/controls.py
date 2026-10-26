"""Single-owner usage controls and privacy-safe audit events."""

import hashlib
import hmac
import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse

from app import database


logger = logging.getLogger("rag_controls")

DEFAULT_LIMITS = {
    "login": (10, 100),
    "chat": (30, 1000),
    "ingest": (10, 100),
    "output": (30, 500),
    "share": (20, 200),
    "comment": (20, 200),
    "public_view": (60, 3000),
}


def _operation(request: Request) -> str | None:
    path, method = request.url.path, request.method
    if method == "POST" and path == "/api/auth/login":
        return "login"
    if method == "POST" and path in {"/api/chat", "/api/chat-stream"}:
        return "chat"
    if method == "POST" and path in {"/api/ingest-stream", "/api/ingest-web-page"}:
        return "ingest"
    if method == "POST" and path.startswith("/api/outputs"):
        return "output"
    if method == "POST" and path == "/api/shares":
        return "share"
    if path.startswith("/api/public-shares/"):
        return "comment" if method == "POST" and path.endswith("/comments") else "public_view"
    return None


def _audit_action(request: Request, operation: str | None) -> str | None:
    if operation in {"login", "ingest", "share", "comment", "chat", "output"}:
        return operation
    if request.method == "DELETE" and request.url.path.startswith("/api/shares/"):
        return "share_revoke"
    if request.method == "DELETE" and request.url.path.startswith("/api/documents/"):
        return "document_delete"
    if request.method == "PATCH" and request.url.path.endswith("/extraction"):
        return "extraction_review"
    return None


def _configured_limit(group: str, kind: str, default: int) -> int:
    value = int(os.getenv(f"RAG_{kind}_{group.upper()}", str(default)))
    if value < 1:
        raise ValueError("Usage limits must be positive.")
    return value


def _usage_group(group: str, request: Request) -> str:
    if group != "login":
        return group
    # Never persist a raw client IP. The owner key makes the digest stable across restarts.
    secret = os.getenv("RAG_OWNER_API_KEY", "local-owner-workspace")
    host = request.client.host if request.client else "unknown"
    return f"login:{hmac.new(secret.encode(), host.encode(), hashlib.sha256).hexdigest()}"


def _audit(action: str | None, status: int, request_id: str) -> None:
    if not action:
        return
    outcome = "allowed" if status < 400 else "denied" if status in {401, 403, 429} else "failed"
    try:
        database.record_audit_event(action, outcome, request_id)
    except Exception as exc:
        logger.error("Audit event unavailable: request_id=%s error_type=%s", request_id, type(exc).__name__)


async def enforce_controls(request: Request, call_next):
    """Apply bounded local quotas before expensive work and audit fixed actions."""
    if request.method == "OPTIONS":
        return await call_next(request)
    operation = _operation(request)
    action = _audit_action(request, operation)
    request_id = getattr(request.state, "request_id", "unavailable")
    if operation:
        minute_default, day_default = DEFAULT_LIMITS[operation]
        try:
            if operation == "ingest" and database.count_active_documents() >= _configured_limit("documents", "MAX", 500):
                response = JSONResponse(status_code=429, content={"detail": "Document quota reached."})
                _audit(action, response.status_code, request_id)
                return response
            retry_after = database.consume_usage(
                _usage_group(operation, request),
                _configured_limit(operation, "RATE", minute_default),
                _configured_limit(operation, "DAILY_QUOTA", day_default),
            )
        except Exception as exc:
            logger.error("Usage controls unavailable: request_id=%s error_type=%s", request_id, type(exc).__name__)
            response = JSONResponse(status_code=503, content={"detail": "Usage controls unavailable."})
            _audit(action, response.status_code, request_id)
            return response
        if retry_after is not None:
            response = JSONResponse(status_code=429, content={"detail": "Usage limit reached."},
                                    headers={"Retry-After": str(retry_after)})
            _audit(action, response.status_code, request_id)
            return response
    response = await call_next(request)
    _audit(action, response.status_code, request_id)
    return response
