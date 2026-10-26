# app/database.py

import os
import sqlite3
import json
import uuid
import logging
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

DB_PATH = os.getenv("RAG_DATABASE_PATH", "rag_history.db")
SCHEMA_VERSION = 4

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_db")


def get_connection() -> sqlite3.Connection:
    database_url = os.getenv("RAG_DATABASE_URL")
    if database_url:
        from app.postgres_database import Connection
        return Connection(database_url)
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")  # fewer locking errors with concurrent writes
    conn.execute("PRAGMA foreign_keys = OFF;")  # avoid FK failures during stream writes
    return conn


def init_db() -> None:
    """Create the conversations and messages tables if they don't exist."""
    database_url = os.getenv("RAG_DATABASE_URL")
    if database_url:
        from app.postgres_database import init_db as init_postgres
        init_postgres(database_url, SCHEMA_VERSION)
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        version = cursor.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"SQLite schema version {version} is newer than this application supports ({SCHEMA_VERSION})."
            )
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources_json TEXT,
                feedback TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        message_columns = {row[1] for row in cursor.execute("PRAGMA table_info(messages)").fetchall()}
        if "feedback" not in message_columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN feedback TEXT")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages (conversation_id)"
        )
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                storage_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ready',
                error TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        document_columns = {
            row[1] for row in cursor.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "storage_name" not in document_columns:
            cursor.execute("ALTER TABLE documents ADD COLUMN storage_name TEXT")
            cursor.execute("UPDATE documents SET storage_name = filename WHERE storage_name IS NULL")
        if "status" not in document_columns:
            cursor.execute("ALTER TABLE documents ADD COLUMN status TEXT NOT NULL DEFAULT 'ready'")
        if "error" not in document_columns:
            cursor.execute("ALTER TABLE documents ADD COLUMN error TEXT")
        if "tags_json" not in document_columns:
            cursor.execute("ALTER TABLE documents ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
        document_schema = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'documents'"
        ).fetchone()[0]
        if "FILENAME TEXT NOT NULL UNIQUE" in document_schema.upper():
            cursor.execute("ALTER TABLE documents RENAME TO documents_legacy")
            cursor.execute("""
                CREATE TABLE documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    storage_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    error TEXT,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                INSERT INTO documents (id, filename, storage_name, status, error, tags_json, created_at)
                SELECT id, filename, COALESCE(storage_name, filename),
                       COALESCE(status, 'ready'), error, COALESCE(tags_json, '[]'), created_at
                FROM documents_legacy
            """)
            cursor.execute("DROP TABLE documents_legacy")
        document_columns = {row[1] for row in cursor.execute("PRAGMA table_info(documents)")}
        for column, definition in {
            "folder_id": "TEXT",
            "source_format": "TEXT NOT NULL DEFAULT 'pdf'",
            "extraction_json": "TEXT",
            "review_status": "TEXT NOT NULL DEFAULT 'unreviewed'",
            "review_note": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in document_columns:
                cursor.execute(f"ALTER TABLE documents ADD COLUMN {column} {definition}")
        cursor.execute("""CREATE TABLE IF NOT EXISTS folders (
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_sets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_set_documents (
                source_set_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (source_set_id, document_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_set_documents_doc ON source_set_documents (document_id)")
        cursor.execute("""CREATE TABLE IF NOT EXISTS shares (
            id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
            resource_type TEXT NOT NULL, resource_id TEXT NOT NULL,
            permission TEXT NOT NULL, expires_at TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS share_comments (
            id TEXT PRIMARY KEY, share_id TEXT NOT NULL, author TEXT NOT NULL,
            body TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_share_comments_share ON share_comments (share_id)")
        cursor.execute("""CREATE TABLE IF NOT EXISTS usage_windows (
            key TEXT NOT NULL, window_start INTEGER NOT NULL, count INTEGER NOT NULL,
            PRIMARY KEY (key, window_start)
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,
            outcome TEXT NOT NULL, request_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events (created_at)")
        cursor.execute("""CREATE TABLE IF NOT EXISTS ingestion_jobs (
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL, filename TEXT NOT NULL,
            storage_name TEXT NOT NULL, source_format TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3, next_run_at INTEGER NOT NULL,
            lease_until INTEGER, error TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_claim ON ingestion_jobs (status, next_run_at, lease_until)")
        cursor.execute("""CREATE TABLE IF NOT EXISTS members (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    logger.info("SQLite database initialized successfully.")


def create_conversation(conv_id: str, title: str) -> Dict[str, Any]:
    """Insert a conversation if it doesn't already exist."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, title) VALUES (?, ?)",
            (conv_id, title),
        )
        conn.commit()
    logger.info("Conversation created/ensured: %s", conv_id)
    return {"id": conv_id, "title": title, "messages": []}


def delete_conversation(conv_id: str) -> bool:
    """Remove a conversation, its messages, and any links and comments to it."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        if cursor.rowcount == 0:
            return False
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        conn.execute("""DELETE FROM share_comments WHERE share_id IN
                        (SELECT id FROM shares WHERE resource_type = 'conversation' AND resource_id = ?)""", (conv_id,))
        conn.execute("DELETE FROM shares WHERE resource_type = 'conversation' AND resource_id = ?", (conv_id,))
    return True


def get_all_conversations() -> List[Dict[str, Any]]:
    """Return every conversation (newest first) with its messages (oldest first)."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM conversations ORDER BY created_at DESC, rowid DESC"
        )
        conv_rows = cursor.fetchall()

        conversations: List[Dict[str, Any]] = []
        for conv in conv_rows:
            # rowid tiebreaker: CURRENT_TIMESTAMP only has 1-second resolution,
            # so the user and assistant messages often share the same timestamp.
            cursor.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (conv["id"],),
            )
            messages = []
            for msg in cursor.fetchall():
                sources = []
                if msg["sources_json"]:
                    try:
                        sources = json.loads(msg["sources_json"])
                    except Exception:
                        sources = []

                messages.append(
                    {
                        "id": msg["id"],
                        "role": msg["role"],
                        "content": msg["content"],
                        "sources": sources,
                        "feedback": msg["feedback"],
                    }
                )

            conversations.append(
                {"id": conv["id"], "title": conv["title"], "messages": messages}
            )
    return conversations


def get_recent_messages(conv_id: str, limit: int = 6) -> List[Dict[str, str]]:
    """Return a bounded, chronologically ordered history from one conversation."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT role, content FROM messages WHERE conversation_id = ?
               AND role IN ('user', 'assistant') AND content != ''
               ORDER BY created_at DESC, rowid DESC LIMIT ?""",
            (conv_id, min(max(limit, 0), 6)),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"][:500]} for row in reversed(rows)]


def save_message(
    msg_id: str,
    conv_id: str,
    role: str,
    content: str,
    sources: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Insert a message (or replace one with the same id)."""
    logger.info("save_message: id=%s conv=%s role=%s", msg_id, conv_id, role)
    try:
        with get_connection() as conn:
            sources_str = json.dumps(sources) if sources else None
            conn.execute(
                """
                INSERT OR REPLACE INTO messages
                    (id, conversation_id, role, content, sources_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (msg_id, conv_id, role, content, sources_str),
            )
            conn.commit()
        logger.info("Saved message [%s] -> id: %s, conv: %s", role, msg_id, conv_id)
    except Exception:
        logger.exception("Failed to save message %s", msg_id)


def update_message_content(
    msg_id: str,
    content: str,
    sources: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Update an existing message's content and sources (used after streaming ends)."""
    try:
        with get_connection() as conn:
            sources_str = json.dumps(sources) if sources else None
            cursor = conn.execute(
                "UPDATE messages SET content = ?, sources_json = ? WHERE id = ?",
                (content, sources_str, msg_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                logger.warning("update_message_content: no row found for id %s", msg_id)
        logger.info("Updated message content -> id: %s", msg_id)
    except Exception:
        logger.exception("Failed to update message %s", msg_id)


def set_message_feedback(msg_id: str, feedback: Optional[str]) -> bool:
    """Set feedback only for an existing assistant message."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE messages SET feedback = ? WHERE id = ? AND role = 'assistant'",
            (feedback, msg_id),
        )
        conn.commit()
        return cursor.rowcount == 1


# ---------------------------------------------------------------------------
# Documents (the knowledge-base registry shown in the UI)
# ---------------------------------------------------------------------------

def add_document(
    filename: str,
    *,
    doc_id: Optional[str] = None,
    storage_name: Optional[str] = None,
    status: str = "ready",
) -> Dict[str, Any]:
    """Register a document using an immutable id and collision-safe storage name."""
    document_id = doc_id or str(uuid.uuid4())
    stored_name = storage_name or filename
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        if status in {"processing", "ready"}:
            limit = int(os.getenv("RAG_MAX_DOCUMENTS", "500"))
            if limit < 1:
                raise ValueError("Document quota must be positive.")
            count = conn.execute("SELECT COUNT(*) FROM documents WHERE status IN ('processing', 'ready')").fetchone()[0]
            if count >= limit:
                raise ValueError("Document quota reached.")
        conn.execute(
            """
            INSERT INTO documents (id, filename, storage_name, status)
            VALUES (?, ?, ?, ?)
            """,
            (document_id, filename, stored_name, status),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return _document_record(row)


def update_document_status(doc_id: str, status: str, error: Optional[str] = None) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE documents SET status = ?, error = ? WHERE id = ?",
            (status, error, doc_id),
        )
        conn.commit()


def list_documents() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY created_at ASC, rowid ASC"
        ).fetchall()
    return [_document_record(row) for row in rows]


def get_document(doc_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    return _document_record(row) if row else None


def _document_record(row: sqlite3.Row) -> Dict[str, Any]:
    record = dict(row)
    record["tags"] = json.loads(record.pop("tags_json") or "[]")
    if "extraction_json" in record:
        record["extraction"] = json.loads(record.pop("extraction_json") or "null")
    return record


def list_folders() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM folders ORDER BY name")]


def create_folder(name: str) -> Dict[str, Any]:
    folder_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute("INSERT INTO folders (id, name) VALUES (?, ?)", (folder_id, name))
    return {"id": folder_id, "name": name}


def rename_folder(folder_id: str, name: str) -> bool:
    with get_connection() as conn:
        return conn.execute("UPDATE folders SET name = ? WHERE id = ?", (name, folder_id)).rowcount == 1


def delete_folder(folder_id: str) -> bool:
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM folders WHERE id = ?", (folder_id,)).fetchone():
            return False
        conn.execute("UPDATE documents SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
        conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        return True


def set_document_folder(doc_id: str, folder_id: Optional[str]) -> bool:
    with get_connection() as conn:
        if folder_id and not conn.execute("SELECT 1 FROM folders WHERE id = ?", (folder_id,)).fetchone():
            raise ValueError("Folder not found.")
        return conn.execute("UPDATE documents SET folder_id = ? WHERE id = ? AND status = 'ready'", (folder_id, doc_id)).rowcount == 1


def set_document_extraction(doc_id: str, report: Dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE documents SET extraction_json = ? WHERE id = ?", (json.dumps(report), doc_id))


def set_extraction_review(doc_id: str, status: str, note: str) -> bool:
    with get_connection() as conn:
        return conn.execute("UPDATE documents SET review_status = ?, review_note = ? WHERE id = ? AND status = 'ready'", (status, note, doc_id)).rowcount == 1


def set_source_format(doc_id: str, source_format: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE documents SET source_format = ? WHERE id = ?", (source_format, doc_id))


def set_document_tags(doc_id: str, tags: List[str]) -> bool:
    """Replace tags on a registered document without changing its identity."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE documents SET tags_json = ? WHERE id = ? AND status = 'ready'",
            (json.dumps(tags), doc_id),
        )
        conn.commit()
        return cursor.rowcount == 1


def delete_document_record(doc_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM source_set_documents WHERE document_id = ?", (doc_id,))
        conn.execute("DELETE FROM ingestion_jobs WHERE document_id = ? AND status IN ('ready', 'dead')", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
    logger.info("Deleted document record: %s", doc_id)


def _validate_source_set_documents(conn: sqlite3.Connection, document_ids: List[str]) -> None:
    if not document_ids or len(document_ids) > 50 or len(set(document_ids)) != len(document_ids):
        raise ValueError("Select 1 to 50 distinct documents.")
    placeholders = ",".join("?" for _ in document_ids)
    ready_count = conn.execute(
        f"SELECT COUNT(*) FROM documents WHERE id IN ({placeholders}) AND status = 'ready'",
        document_ids,
    ).fetchone()[0]
    if ready_count != len(document_ids):
        raise ValueError("Source sets can contain only registered, ready documents.")


def _source_set_record(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    members = conn.execute("""
        SELECT ssd.document_id FROM source_set_documents AS ssd
        JOIN documents AS d ON d.id = ssd.document_id AND d.status = 'ready'
        WHERE ssd.source_set_id = ? ORDER BY ssd.position
    """, (row["id"],)).fetchall()
    return {"id": row["id"], "name": row["name"],
            "created_at": row["created_at"], "document_ids": [member[0] for member in members]}


def list_source_sets() -> List[Dict[str, Any]]:
    """List saved document selections with only currently ready members."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM source_sets ORDER BY created_at ASC, rowid ASC").fetchall()
        return [_source_set_record(conn, row) for row in rows]


def create_source_set(name: str, document_ids: List[str]) -> Dict[str, Any]:
    """Persist a named collection of ready document IDs."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        _validate_source_set_documents(conn, document_ids)
        source_set_id = str(uuid.uuid4())
        conn.execute("INSERT INTO source_sets (id, name) VALUES (?, ?)", (source_set_id, name))
        conn.executemany(
            "INSERT INTO source_set_documents (source_set_id, document_id, position) VALUES (?, ?, ?)",
            [(source_set_id, document_id, position) for position, document_id in enumerate(document_ids)],
        )
        row = conn.execute("SELECT * FROM source_sets WHERE id = ?", (source_set_id,)).fetchone()
        return _source_set_record(conn, row)


def update_source_set(source_set_id: str, name: str, document_ids: List[str]) -> Optional[Dict[str, Any]]:
    """Replace a saved selection atomically, or return None if it is absent."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM source_sets WHERE id = ?", (source_set_id,)).fetchone()
        if row is None:
            return None
        _validate_source_set_documents(conn, document_ids)
        conn.execute("UPDATE source_sets SET name = ? WHERE id = ?", (name, source_set_id))
        conn.execute("DELETE FROM source_set_documents WHERE source_set_id = ?", (source_set_id,))
        conn.executemany(
            "INSERT INTO source_set_documents (source_set_id, document_id, position) VALUES (?, ?, ?)",
            [(source_set_id, document_id, position) for position, document_id in enumerate(document_ids)],
        )
        row = conn.execute("SELECT * FROM source_sets WHERE id = ?", (source_set_id,)).fetchone()
        return _source_set_record(conn, row)


def delete_source_set(source_set_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM source_sets WHERE id = ?", (source_set_id,))
        conn.execute("DELETE FROM source_set_documents WHERE source_set_id = ?", (source_set_id,))
        conn.execute("DELETE FROM share_comments WHERE share_id IN (SELECT id FROM shares WHERE resource_type = 'collection' AND resource_id = ?)", (source_set_id,))
        conn.execute("DELETE FROM shares WHERE resource_type = 'collection' AND resource_id = ?", (source_set_id,))
        return cursor.rowcount == 1


def create_share(resource_type: str, resource_id: str, permission: str, days: int) -> Dict[str, Any]:
    token = secrets.token_urlsafe(32)
    share_id = str(uuid.uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    with get_connection() as conn:
        conn.execute("INSERT INTO shares (id, token_hash, resource_type, resource_id, permission, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (share_id, hashlib.sha256(token.encode()).hexdigest(), resource_type, resource_id, permission, expires_at))
    return {"id": share_id, "token": token, "resource_type": resource_type, "resource_id": resource_id,
            "permission": permission, "expires_at": expires_at}


def list_shares() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT id, resource_type, resource_id, permission, expires_at, created_at FROM shares ORDER BY created_at DESC")]


def get_share_by_token(token: str) -> Optional[Dict[str, Any]]:
    if len(token) > 100:
        return None
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id, resource_type, resource_id, permission, expires_at FROM shares WHERE token_hash = ?",
                           (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        return None
    return dict(row)


def revoke_share(share_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM shares WHERE id = ?", (share_id,))
        conn.execute("DELETE FROM share_comments WHERE share_id = ?", (share_id,))
        return cursor.rowcount == 1


def add_share_comment(share_id: str, author: str, body: str) -> Dict[str, Any]:
    comment_id = str(uuid.uuid4())
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM share_comments WHERE share_id = ?", (share_id,)).fetchone()[0]
        if count >= 100:
            raise ValueError("This share has reached its 100-comment limit.")
        conn.execute("INSERT INTO share_comments (id, share_id, author, body) VALUES (?, ?, ?, ?)",
                     (comment_id, share_id, author, body))
    return {"id": comment_id, "author": author, "body": body}


def list_share_comments(share_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT id, author, body, created_at FROM share_comments WHERE share_id = ? ORDER BY created_at ASC, rowid ASC LIMIT 100", (share_id,))]


def consume_usage(group: str, minute_limit: int, day_limit: int, now: Optional[int] = None) -> Optional[int]:
    """Atomically consume both fixed windows, or return seconds until retry."""
    timestamp = int(datetime.now(timezone.utc).timestamp()) if now is None else now
    minute_start = timestamp // 60 * 60
    day_start = timestamp // 86400 * 86400
    windows = ((f"{group}:minute", minute_start, minute_limit, 60),
               (f"{group}:day", day_start, day_limit, 86400))
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for key, start, limit, duration in windows:
            row = conn.execute("SELECT count FROM usage_windows WHERE key = ? AND window_start = ?", (key, start)).fetchone()
            if row and row[0] >= limit:
                return max(1, start + duration - timestamp)
        for key, start, _limit, _duration in windows:
            conn.execute("""INSERT INTO usage_windows (key, window_start, count) VALUES (?, ?, 1)
                            ON CONFLICT(key, window_start) DO UPDATE SET count = usage_windows.count + 1""", (key, start))
    return None


def count_active_documents() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM documents WHERE status IN ('processing', 'ready')").fetchone()[0]


def record_audit_event(action: str, outcome: str, request_id: str) -> None:
    with get_connection() as conn:
        conn.execute("INSERT INTO audit_events (action, outcome, request_id, created_at) VALUES (?, ?, ?, ?)",
                     (action, outcome, request_id, datetime.now(timezone.utc).isoformat()))


def list_audit_events(limit: int = 100) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT action, outcome, request_id, created_at FROM audit_events ORDER BY id DESC LIMIT ?",
            (min(max(limit, 1), 100),),
        )]


def retention_summary(now: Optional[datetime] = None, audit_days: int = 90, apply: bool = False) -> Dict[str, int]:
    """Count or delete expired links and bounded operational records."""
    if not 1 <= audit_days <= 3650:
        raise ValueError("Audit retention must be 1 to 3650 days.")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("Retention time must include a timezone.")
    expired_at = moment.astimezone(timezone.utc).isoformat()
    audit_before = (moment - timedelta(days=audit_days)).astimezone(timezone.utc).isoformat()
    usage_before = int(moment.timestamp()) - 2 * 86400
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        counts = {
            "expired_shares": conn.execute("SELECT COUNT(*) FROM shares WHERE expires_at <= ?", (expired_at,)).fetchone()[0],
            "expired_share_comments": conn.execute("""SELECT COUNT(*) FROM share_comments WHERE share_id IN
                (SELECT id FROM shares WHERE expires_at <= ?)""", (expired_at,)).fetchone()[0],
            "old_audit_events": conn.execute("SELECT COUNT(*) FROM audit_events WHERE created_at < ?", (audit_before,)).fetchone()[0],
            "old_usage_windows": conn.execute("SELECT COUNT(*) FROM usage_windows WHERE window_start < ?", (usage_before,)).fetchone()[0],
        }
        if apply:
            conn.execute("""DELETE FROM share_comments WHERE share_id IN
                (SELECT id FROM shares WHERE expires_at <= ?)""", (expired_at,))
            conn.execute("DELETE FROM shares WHERE expires_at <= ?", (expired_at,))
            conn.execute("DELETE FROM audit_events WHERE created_at < ?", (audit_before,))
            conn.execute("DELETE FROM usage_windows WHERE window_start < ?", (usage_before,))
    return counts


def enqueue_ingestion_job(document_id: str, filename: str, storage_name: str,
                          source_format: str, now: Optional[int] = None) -> Dict[str, Any]:
    timestamp = int(datetime.now(timezone.utc).timestamp()) if now is None else now
    job_id = str(uuid.uuid4())
    created_at = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM documents WHERE id = ? AND status = 'processing'", (document_id,)).fetchone():
            raise ValueError("Processing document is unavailable.")
        conn.execute("""INSERT INTO ingestion_jobs
            (id, document_id, filename, storage_name, source_format, status,
             next_run_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
            (job_id, document_id, filename, storage_name, source_format, timestamp, created_at, created_at))
    return get_ingestion_job(job_id)


def get_ingestion_job(job_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def active_ingestion_job_for_document(document_id: str) -> bool:
    with get_connection() as conn:
        return conn.execute("""SELECT 1 FROM ingestion_jobs WHERE document_id = ?
            AND status IN ('queued', 'running') LIMIT 1""", (document_id,)).fetchone() is not None


def list_ingestion_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT * FROM ingestion_jobs ORDER BY created_at DESC, id DESC LIMIT ?",
            (min(max(limit, 1), 100),),
        )]


def retry_dead_ingestion_job(job_id: str, now: Optional[int] = None) -> bool:
    timestamp = int(datetime.now(timezone.utc).timestamp()) if now is None else now
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT document_id FROM ingestion_jobs WHERE id = ? AND status = 'dead'", (job_id,)).fetchone()
        if not row:
            return False
        conn.execute("""UPDATE ingestion_jobs SET status = 'queued', attempts = 0,
            next_run_at = ?, lease_until = NULL, error = NULL, updated_at = ? WHERE id = ?""",
            (timestamp, datetime.fromtimestamp(timestamp, timezone.utc).isoformat(), job_id))
        conn.execute("UPDATE documents SET status = 'processing', error = NULL WHERE id = ?", (row[0],))
    return True


def claim_ingestion_job(now: Optional[int] = None, lease_seconds: int = 1800) -> Optional[Dict[str, Any]]:
    """Atomically claim a due job or one whose worker lease expired."""
    timestamp = int(datetime.now(timezone.utc).timestamp()) if now is None else now
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""SELECT * FROM ingestion_jobs WHERE
            (status = 'queued' AND next_run_at <= ?) OR
            (status = 'running' AND lease_until <= ?)
            ORDER BY created_at, id LIMIT 1""", (timestamp, timestamp)).fetchone()
        if not row:
            return None
        if row["attempts"] >= row["max_attempts"]:
            conn.execute("UPDATE ingestion_jobs SET status = 'dead', updated_at = ? WHERE id = ?",
                         (datetime.fromtimestamp(timestamp, timezone.utc).isoformat(), row["id"]))
            conn.execute("UPDATE documents SET status = 'failed', error = 'Worker lease expired after final attempt.' WHERE id = ?",
                         (row["document_id"],))
            return None
        conn.execute("""UPDATE ingestion_jobs SET status = 'running', attempts = attempts + 1,
            lease_until = ?, updated_at = ? WHERE id = ?""",
            (timestamp + lease_seconds, datetime.fromtimestamp(timestamp, timezone.utc).isoformat(), row["id"]))
        return dict(conn.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (row["id"],)).fetchone())


def finish_ingestion_job(job_id: str, now: Optional[int] = None) -> None:
    timestamp = int(datetime.now(timezone.utc).timestamp()) if now is None else now
    with get_connection() as conn:
        conn.execute("""UPDATE ingestion_jobs SET status = 'ready', lease_until = NULL,
            error = NULL, updated_at = ? WHERE id = ? AND status = 'running'""",
            (datetime.fromtimestamp(timestamp, timezone.utc).isoformat(), job_id))


def fail_ingestion_job(job_id: str, error_type: str, now: Optional[int] = None) -> Dict[str, Any]:
    """Schedule bounded exponential retry or move the job to the dead-letter state."""
    timestamp = int(datetime.now(timezone.utc).timestamp()) if now is None else now
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM ingestion_jobs WHERE id = ? AND status = 'running'", (job_id,)).fetchone()
        if not row:
            raise ValueError("Job is not running.")
        dead = row["attempts"] >= row["max_attempts"]
        delay = min(300, 2 ** row["attempts"] * 5)
        conn.execute("""UPDATE ingestion_jobs SET status = ?, next_run_at = ?,
            lease_until = NULL, error = ?, updated_at = ? WHERE id = ?""",
            ("dead" if dead else "queued", timestamp if dead else timestamp + delay,
             error_type[:80], datetime.fromtimestamp(timestamp, timezone.utc).isoformat(), job_id))
    return get_ingestion_job(job_id)


def create_member(name: str, role: str, key_hash: str) -> Dict[str, Any]:
    """Store a random access key digest; never persist or return the key itself."""
    member_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute("INSERT INTO members (id, name, role, key_hash) VALUES (?, ?, ?, ?)",
                     (member_id, name, role, key_hash))
    return {"id": member_id, "name": name, "role": role, "status": "active"}


def member_by_key_hash(key_hash: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id, name, role, status FROM members WHERE key_hash = ? AND status = 'active'",
                           (key_hash,)).fetchone()
    return dict(row) if row else None


def get_member(member_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id, name, role, status FROM members WHERE id = ? AND status = 'active'",
                           (member_id,)).fetchone()
    return dict(row) if row else None


def list_members() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT id, name, role, status, created_at FROM members ORDER BY created_at, id")]


def revoke_member(member_id: str) -> bool:
    with get_connection() as conn:
        return conn.execute("UPDATE members SET status = 'revoked' WHERE id = ? AND status = 'active'",
                            (member_id,)).rowcount == 1
