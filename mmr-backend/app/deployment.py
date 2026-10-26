"""Reject production-like configurations that bypass required isolation controls."""

import os
from urllib.parse import urlsplit


def validate_deployment_config() -> None:
    mode = os.getenv("RAG_DEPLOYMENT_MODE", "local").lower()
    if mode not in {"staging", "production"}:
        return
    errors = []
    if len(os.getenv("RAG_OWNER_API_KEY", "")) < 32:
        errors.append("RAG_OWNER_API_KEY must be at least 32 characters")
    if not os.getenv("RAG_DATABASE_URL", "").startswith(("postgresql://", "postgres://")):
        errors.append("RAG_DATABASE_URL must point to PostgreSQL")
    if not os.getenv("RAG_ORIGINALS_BUCKET"):
        errors.append("RAG_ORIGINALS_BUCKET is required")
    if os.getenv("RAG_WORKSPACE_ID", "default") == "default":
        errors.append("RAG_WORKSPACE_ID must identify this isolated workspace")
    workspace = os.getenv("RAG_WORKSPACE_ID", "default")
    if not os.getenv("RAG_ORIGINALS_PREFIX", "").startswith(workspace + "/"):
        errors.append("RAG_ORIGINALS_PREFIX must begin with the workspace ID")
    if os.getenv("RAG_COOKIE_SECURE") != "true":
        errors.append("RAG_COOKIE_SECURE must be true")
    if os.getenv("RAG_INGEST_MODE") != "worker":
        errors.append("RAG_INGEST_MODE must be worker")
    origins = [item.strip() for item in os.getenv("RAG_CORS_ORIGINS", "").split(",") if item.strip()]
    if not origins or any(urlsplit(origin).scheme != "https" or not urlsplit(origin).hostname for origin in origins):
        errors.append("RAG_CORS_ORIGINS must contain only explicit HTTPS origins")
    if errors:
        raise RuntimeError("Invalid deployment configuration: " + "; ".join(errors))
