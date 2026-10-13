# app/database.py

import sqlite3
import json
import logging
from typing import List, Dict, Any, Optional

DB_PATH = "rag_history.db"

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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages (conversation_id)"
        )
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
                    }
                )

            conversations.append(
                {"id": conv["id"], "title": conv["title"], "messages": messages}
            )
    return conversations


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