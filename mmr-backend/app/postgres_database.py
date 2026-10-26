"""PostgreSQL connection adapter for the existing registry operations.

The adapter keeps the small DB-API surface used by database.py while PostgreSQL
owns transactions and concurrent writes. It never interpolates query values.
"""

import re
from typing import Any


class _Row(dict):
    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _Cursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def execute(self, query: str, parameters=()):
        sql = query.strip()
        if sql.upper() == "BEGIN IMMEDIATE":
            # Serialize the SQLite transactions used for quotas and job claims.
            sql = "SELECT pg_advisory_xact_lock(80973194)"
        elif sql.upper().startswith("INSERT OR IGNORE INTO CONVERSATIONS"):
            sql = re.sub(r"INSERT OR IGNORE", "INSERT", sql, count=1, flags=re.I)
            sql += " ON CONFLICT (id) DO NOTHING"
        elif sql.upper().startswith("INSERT OR REPLACE INTO MESSAGES"):
            sql = re.sub(r"INSERT OR REPLACE", "INSERT", sql, count=1, flags=re.I)
            sql += (" ON CONFLICT (id) DO UPDATE SET conversation_id = EXCLUDED.conversation_id,"
                    " role = EXCLUDED.role, content = EXCLUDED.content,"
                    " sources_json = EXCLUDED.sources_json")
        sql = re.sub(r"\browid\b", "id", sql, flags=re.I)
        sql = sql.replace("?", "%s")
        self._cursor.execute(sql, parameters)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return _Row(row) if row is not None else None

    def fetchall(self):
        return [_Row(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        for row in self._cursor:
            yield _Row(row)


class Connection:
    def __init__(self, url: str):
        import psycopg
        from psycopg.rows import dict_row

        self._connection = psycopg.connect(url, row_factory=dict_row)
        self.row_factory = None  # SQLite callers set this; PostgreSQL always returns keyed rows.

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type:
                self._connection.rollback()
            else:
                self._connection.commit()
        finally:
            self._connection.close()

    def cursor(self):
        return _Cursor(self._connection.cursor())

    def execute(self, query: str, parameters=()):
        return self.cursor().execute(query, parameters)

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()


SCHEMA = (
    "CREATE TABLE IF NOT EXISTS rag_schema_version (version INTEGER NOT NULL)",
    """CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, sources_json TEXT, feedback TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages (conversation_id)",
    """CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY, filename TEXT NOT NULL, storage_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ready', error TEXT, tags_json TEXT NOT NULL DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, folder_id TEXT,
        source_format TEXT NOT NULL DEFAULT 'pdf', extraction_json TEXT,
        review_status TEXT NOT NULL DEFAULT 'unreviewed', review_note TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS folders (
        id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS source_sets (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS source_set_documents (
        source_set_id TEXT NOT NULL, document_id TEXT NOT NULL, position INTEGER NOT NULL,
        PRIMARY KEY (source_set_id, document_id))""",
    "CREATE INDEX IF NOT EXISTS idx_source_set_documents_doc ON source_set_documents (document_id)",
    """CREATE TABLE IF NOT EXISTS shares (
        id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL, permission TEXT NOT NULL, expires_at TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS share_comments (
        id TEXT PRIMARY KEY, share_id TEXT NOT NULL, author TEXT NOT NULL,
        body TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    "CREATE INDEX IF NOT EXISTS idx_share_comments_share ON share_comments (share_id)",
    """CREATE TABLE IF NOT EXISTS usage_windows (
        key TEXT NOT NULL, window_start BIGINT NOT NULL, count INTEGER NOT NULL,
        PRIMARY KEY (key, window_start))""",
    """CREATE TABLE IF NOT EXISTS audit_events (
        id BIGSERIAL PRIMARY KEY, action TEXT NOT NULL, outcome TEXT NOT NULL,
        request_id TEXT NOT NULL, created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events (created_at)",
    """CREATE TABLE IF NOT EXISTS ingestion_jobs (
        id TEXT PRIMARY KEY, document_id TEXT NOT NULL, filename TEXT NOT NULL,
        storage_name TEXT NOT NULL, source_format TEXT NOT NULL, status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
        next_run_at BIGINT NOT NULL, lease_until BIGINT, error TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_claim ON ingestion_jobs (status, next_run_at, lease_until)",
    """CREATE TABLE IF NOT EXISTS members (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
        key_hash TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
)


def init_db(url: str, version: int) -> None:
    """Create or validate the PostgreSQL schema without downgrading newer data."""
    with Connection(url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(80973194)")
        for statement in SCHEMA:
            conn.execute(statement)
        current = conn.execute("SELECT version FROM rag_schema_version LIMIT 1").fetchone()
        if current and current[0] > version:
            raise RuntimeError(f"PostgreSQL schema version {current[0]} is newer than this application supports ({version}).")
        if current is None:
            conn.execute("INSERT INTO rag_schema_version (version) VALUES (?)", (version,))
        elif current[0] == 3 and version == 4:
            conn.execute("UPDATE rag_schema_version SET version = ?", (version,))
        elif current[0] < version:
            raise RuntimeError("PostgreSQL schema upgrade requires an explicit migration.")
