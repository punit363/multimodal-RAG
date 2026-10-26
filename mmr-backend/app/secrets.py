"""Load orchestrator-mounted secret files before importing application settings."""

import json
import os
from pathlib import Path


SECRET_NAMES = (
    "OPENAI_API_KEY", "RAG_OWNER_API_KEY", "RAG_DATABASE_URL",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
)


def load_managed_secrets() -> None:
    """Fetch an allowlisted JSON secret from AWS Secrets Manager via workload identity."""
    secret_id = os.getenv("RAG_SECRETS_MANAGER_ID")
    if not secret_id:
        return
    import boto3

    payload = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    values = json.loads(payload["SecretString"])
    if not isinstance(values, dict) or not values:
        raise RuntimeError("Managed secret must be a nonempty JSON object.")
    for name, value in values.items():
        if name not in SECRET_NAMES or not isinstance(value, str) or not value:
            raise RuntimeError("Managed secret contains an invalid key or value.")
        if os.getenv(name) or os.getenv(f"{name}_FILE"):
            raise RuntimeError(f"Managed secret conflicts with {name} or {name}_FILE.")
    for name, value in values.items():
        os.environ[name] = value


def load_secret_files() -> None:
    for name in SECRET_NAMES:
        source = os.getenv(f"{name}_FILE")
        if not source:
            continue
        if os.getenv(name):
            raise RuntimeError(f"Set either {name} or {name}_FILE, not both.")
        path = Path(source)
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise RuntimeError(f"Secret file for {name} is missing or too large.")
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
        if not value:
            raise RuntimeError(f"Secret file for {name} is empty.")
        os.environ[name] = value
