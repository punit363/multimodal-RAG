import sqlite3
import json
from typing import List, Dict, Any, Optional

DB_PATH = "rag_history.db"

def init_db():
    """Initialize SQLite tables for conversations and messages"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Table for conversation metadata
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Table for chat messages
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sources_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations (id)
        )
    """)

    conn.commit()
    conn.close()

def create_conversation(conv_id: str, title: str) -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO conversations (id, title) VALUES (?, ?)",
        (conv_id, title)
    )
    conn.commit()
    conn.close()
    return {"id": conv_id, "title": title, "messages": []}

def get_all_conversations() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM conversations ORDER BY created_at DESC")
    conv_rows = cursor.fetchall()

    conversations = []
    for conv in conv_rows:
        cursor.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conv["id"],)
        )
        msg_rows = cursor.fetchall()

        messages = []
        for msg in msg_rows:
            messages.append({
                "id": msg["id"],
                "role": msg["role"],
                "content": msg["content"],
                "sources": json.loads(msg["sources_json"]) if msg["sources_json"] else []
            })

        conversations.append({
            "id": conv["id"],
            "title": conv["title"],
            "messages": messages
        })

    conn.close()
    return conversations

def save_message(msg_id: str, conv_id: str, role: str, content: str, sources: Optional[List[Dict[str, Any]]] = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    sources_str = json.dumps(sources) if sources else None
    
    cursor.execute("""
        INSERT INTO messages (id, conversation_id, role, content, sources_json)
        VALUES (?, ?, ?, ?, ?)
    """, (msg_id, conv_id, role, content, sources_str))
    
    conn.commit()
    conn.close()

def update_message_content(msg_id: str, content: str, sources: Optional[List[Dict[str, Any]]] = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = cursor = conn.cursor()
    sources_str = json.dumps(sources) if sources else None
    
    if sources_str:
        cursor.execute(
            "UPDATE messages SET content = ?, sources_json = ? WHERE id = ?",
            (content, sources_str, msg_id)
        )
    else:
        cursor.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            (content, msg_id)
        )
    conn.commit()
    conn.close()

def update_conversation_title(conv_id: str, title: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conv_id))
    conn.commit()
    conn.close()