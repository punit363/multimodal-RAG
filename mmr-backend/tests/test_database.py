import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

from app import database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self._temporary_directory.name) / "test_history.db"
        self._database_path_patch = patch.object(database, "DB_PATH", str(self.database_path))
        self._database_path_patch.start()
        database.init_db()

    def tearDown(self):
        self._database_path_patch.stop()
        self._temporary_directory.cleanup()

    def test_conversation_messages_and_sources_round_trip(self):
        database.create_conversation("conversation-1", "Test conversation")
        database.save_message(
            msg_id="message-1",
            conv_id="conversation-1",
            role="assistant",
            content="Initial answer",
        )
        sources = [{"filename": "report.pdf", "chunk_id": 2}]
        database.update_message_content("message-1", "Updated answer", sources)

        conversations = database.get_all_conversations()

        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0]["id"], "conversation-1")
        self.assertEqual(conversations[0]["messages"][0]["content"], "Updated answer")
        self.assertEqual(conversations[0]["messages"][0]["sources"], sources)

    def test_document_registry_allows_duplicate_display_names_and_deletion(self):
        first = database.add_document("report.pdf")
        second = database.add_document("report.pdf")

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(database.get_document(first["id"])["filename"], "report.pdf")
        self.assertEqual(len(database.list_documents()), 2)

        database.delete_document_record(first["id"])

        self.assertIsNone(database.get_document(first["id"]))
        self.assertEqual(len(database.list_documents()), 1)

    def test_feedback_survives_database_reload_and_only_targets_answers(self):
        database.create_conversation("conversation-1", "Test")
        database.save_message("user-1", "conversation-1", "user", "Question")
        database.save_message("assistant-1", "conversation-1", "assistant", "Answer")
        self.assertFalse(database.set_message_feedback("user-1", "helpful"))
        self.assertTrue(database.set_message_feedback("assistant-1", "not_helpful"))
        self.assertEqual(database.get_all_conversations()[0]["messages"][1]["feedback"], "not_helpful")
        self.assertTrue(database.set_message_feedback("assistant-1", None))
        self.assertIsNone(database.get_all_conversations()[0]["messages"][1]["feedback"])

    def test_existing_messages_table_gains_feedback_column(self):
        with sqlite3.connect(self.database_path) as conn:
            conn.execute("DROP TABLE messages")
            conn.execute("""
                CREATE TABLE messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
                    content TEXT NOT NULL, sources_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("INSERT INTO messages (id, conversation_id, role, content) VALUES ('old', 'conv', 'assistant', 'Answer')")
        database.init_db()
        self.assertTrue(database.set_message_feedback("old", "helpful"))
        with database.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT feedback FROM messages WHERE id = 'old'").fetchone()[0], "helpful")

    def test_legacy_unique_filename_registry_is_migrated(self):
        with sqlite3.connect(self.database_path) as conn:
            conn.execute("DROP TABLE documents")
            conn.execute("""
                CREATE TABLE documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "INSERT INTO documents (id, filename) VALUES (?, ?)",
                ("legacy-id", "report.pdf"),
            )
            conn.commit()

        database.init_db()
        duplicate = database.add_document("report.pdf")

        documents = database.list_documents()
        self.assertEqual(len(documents), 2)
        self.assertNotEqual(duplicate["id"], "legacy-id")
        self.assertEqual(database.get_document("legacy-id")["storage_name"], "report.pdf")


if __name__ == "__main__":
    unittest.main()

