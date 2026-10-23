# app/database.py

import os
import sqlite3
import json
import uuid
import logging
from typing import List, Dict, Any, Optional

DB_PATH = os.getenv("RAG_DATABASE_PATH", "rag_history.db")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")  # fewer locking errors with concurrent writes
    conn.execute("PRAGMA foreign_keys = OFF;")  # avoid FK failures during stream writes
    return conn


def init_db() -> None:
    """Create the conversations and messages tables if they don't exist."""
    with get_connection() as conn:
        cursor = conn.cursor()
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
        rows = conn.execute(
            """SELECT role, content FROM messages WHERE conversation_id = ?
               AND role IN ('user', 'assistant') AND content != ''
               ORDER BY created_at DESC, rowid DESC LIMIT ?""",
            (conv_id, min(max(limit, 0), 6)),
        ).fetchall()
    return [{"role": role, "content": content[:500]} for role, content in reversed(rows)]


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
        return cursor.rowcount == 1
