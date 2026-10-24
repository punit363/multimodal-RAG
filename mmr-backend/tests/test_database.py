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

    def test_schema_version_is_idempotent_and_rejects_future_database(self):
        with database.get_connection() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], database.SCHEMA_VERSION)
        database.init_db()
        with database.get_connection() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], database.SCHEMA_VERSION)
            conn.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION + 1}")
        with self.assertRaisesRegex(RuntimeError, "newer than this application supports"):
            database.init_db()

    def test_conversation_messages_and_sources_round_trip(self):
        database.create_conversation("conversation-1", "Test conversation")
        database.save_message(
            msg_id="message-1",
            conv_id="conversation-1",
            role="assistant",
            content="Initial answer",
        )
        sources = [{
            "document_id": "document-1",
            "filename": "report.pdf",
            "chunk_id": "document-1::2",
            "page_numbers": [3, 4],
            "page_location_status": "partial",
            "element_types": ["NarrativeText", "Table"],
            "highlight_rect": None,
        }]
        database.update_message_content("message-1", "Updated answer", sources)

        conversations = database.get_all_conversations()

        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0]["id"], "conversation-1")
        self.assertEqual(conversations[0]["messages"][0]["content"], "Updated answer")
        self.assertEqual(conversations[0]["messages"][0]["sources"], sources)

    def test_recent_history_is_bounded_and_conversation_scoped(self):
        database.create_conversation("first", "First")
        database.create_conversation("second", "Second")
        for index in range(8):
            database.save_message(f"first-{index}", "first", "user", f"Question {index}")
        database.save_message("second-1", "second", "user", "Private other topic")
        history = database.get_recent_messages("first")
        self.assertEqual(len(history), 6)
        self.assertEqual(history[0]["content"], "Question 2")
        self.assertEqual(history[-1]["content"], "Question 7")
        self.assertNotIn("Private other topic", str(history))

    def test_document_registry_allows_duplicate_display_names_and_deletion(self):
        first = database.add_document("report.pdf")
        second = database.add_document("report.pdf")

        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(database.get_document(first["id"])["filename"], "report.pdf")
        self.assertEqual(len(database.list_documents()), 2)

        database.delete_document_record(first["id"])

        self.assertIsNone(database.get_document(first["id"]))
        self.assertEqual(len(database.list_documents()), 1)

    def test_document_tags_persist_after_reload_and_legacy_migration(self):
        document = database.add_document("tagged.pdf", doc_id="tagged")
        self.assertEqual(document["tags"], [])
        self.assertTrue(database.set_document_tags("tagged", ["Finance", "2026"]))
        database.init_db()
        self.assertEqual(database.get_document("tagged")["tags"], ["Finance", "2026"])
        self.assertFalse(database.set_document_tags("missing", ["Finance"]))

    def test_source_sets_round_trip_and_prune_deleted_documents(self):
        first = database.add_document("first.pdf", doc_id="first")
        second = database.add_document("second.pdf", doc_id="second")
        saved = database.create_source_set("Research", [first["id"], second["id"]])
        database.init_db()
        self.assertEqual(database.list_source_sets()[0]["document_ids"], ["first", "second"])
        updated = database.update_source_set(saved["id"], "Latest", ["second", "first"])
        self.assertEqual(updated["name"], "Latest")
        self.assertEqual(updated["document_ids"], ["second", "first"])
        database.delete_document_record("second")
        self.assertEqual(database.list_source_sets()[0]["document_ids"], ["first"])
        self.assertTrue(database.delete_source_set(saved["id"]))
        self.assertEqual(database.list_source_sets(), [])

    def test_source_sets_reject_unknown_failed_and_duplicate_documents(self):
        database.add_document("ready.pdf", doc_id="ready")
        database.add_document("failed.pdf", doc_id="failed", status="failed")
        for ids in (["missing"], ["failed"], ["ready", "ready"]):
            with self.assertRaises(ValueError):
                database.create_source_set("Invalid", ids)
        self.assertEqual(database.list_source_sets(), [])

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
        self.assertEqual(database.get_document("legacy-id")["tags"], [])


if __name__ == "__main__":
    unittest.main()

