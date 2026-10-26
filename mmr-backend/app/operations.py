"""Small, dependency-light runtime probes for the local deployment."""

import os
import tempfile
from contextlib import closing
from pathlib import Path

from app import database
from app import originals


def _writable_directory(path: str) -> bool:
    directory = Path(path)
    if not directory.is_dir():
        return False
    try:
        with tempfile.TemporaryFile(dir=directory) as probe:
            probe.write(b"ready")
            probe.flush()
        return True
    except OSError:
        return False


def readiness_checks(upload_dir: str, vector_dir: str) -> dict[str, str]:
    """Report only dependency state; never expose paths or database details."""
    checks = {"database": "failed", "uploads": "failed", "vectors": "failed"}
    if os.getenv("RAG_DATABASE_URL"):
        try:
            with closing(database.get_connection()) as conn:
                conn.execute("SELECT id FROM documents LIMIT 1").fetchone()
                version = conn.execute("SELECT version FROM rag_schema_version LIMIT 1").fetchone()
            if version and version[0] == database.SCHEMA_VERSION:
                checks["database"] = "ok"
        except Exception:
            pass
    elif os.path.isfile(database.DB_PATH):
        try:
            with closing(database.get_connection()) as conn:
                conn.execute("SELECT id FROM documents LIMIT 1").fetchone()
                version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == database.SCHEMA_VERSION:
                checks["database"] = "ok"
        except Exception:
            pass
    if _writable_directory(upload_dir):
        checks["uploads"] = "ok"
    if _writable_directory(vector_dir):
        checks["vectors"] = "ok"
    if originals.enabled():
        checks["originals"] = "ok" if originals.ready() else "failed"
    return checks
