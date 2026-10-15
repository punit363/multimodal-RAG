import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self._temporary_directory.name) / "test_history.db"
        self._database_path_patch = patch.object(database, "DB_PATH", str(database_path))
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

    def test_document_registry_is_idempotent_and_deletable(self):
        first = database.add_document("report.pdf")
        second = database.add_document("report.pdf")

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(database.get_document(first["id"])["filename"], "report.pdf")
        self.assertEqual(len(database.list_documents()), 1)

        database.delete_document_record(first["id"])

        self.assertIsNone(database.get_document(first["id"]))
        self.assertEqual(database.list_documents(), [])


if __name__ == "__main__":
    unittest.main()

