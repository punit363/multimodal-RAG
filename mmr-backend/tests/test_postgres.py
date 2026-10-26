"""Opt-in tests run against an isolated empty TEST_POSTGRES_URL database."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database
from app.postgres_database import Connection
from scripts.migrate_sqlite_to_postgres import TABLES, migrate


@unittest.skipUnless(os.getenv("TEST_POSTGRES_URL"), "set TEST_POSTGRES_URL to an isolated PostgreSQL database")
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ["TEST_POSTGRES_URL"]
        self.database_url = patch.dict(os.environ, {"RAG_DATABASE_URL": self.url})
        self.database_url.start()
        database.init_db()
        with Connection(self.url) as conn:
            conn.execute("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY")

    def tearDown(self):
        self.database_url.stop()

    def test_registry_and_durable_jobs(self):
        database.create_conversation("conv", "A conversation")
        database.save_message("msg", "conv", "user", "hello")
        self.assertEqual(database.get_recent_messages("conv")[0]["content"], "hello")
        doc = database.add_document("source.pdf", doc_id="doc", storage_name="doc.pdf", status="processing")
        self.assertEqual(doc["id"], "doc")
        job = database.enqueue_ingestion_job("doc", "source.pdf", "doc.pdf", "pdf", now=100)
        self.assertEqual(database.claim_ingestion_job(now=100)["id"], job["id"])
        self.assertEqual(database.fail_ingestion_job(job["id"], "RuntimeError", now=100)["status"], "queued")
        self.assertEqual(database.claim_ingestion_job(now=111)["attempts"], 2)
        database.finish_ingestion_job(job["id"], now=111)
        self.assertEqual(database.get_ingestion_job(job["id"])["status"], "ready")
        self.assertIsNone(database.consume_usage("test", 1, 1, now=100))
        self.assertGreater(database.consume_usage("test", 1, 1, now=100), 0)
        member = database.create_member("Reader", "viewer", "digest")
        self.assertEqual(database.member_by_key_hash("digest")["id"], member["id"])
        self.assertTrue(database.revoke_member(member["id"]))
        self.assertIsNone(database.get_member(member["id"]))

    def test_sqlite_copy_preserves_counts_and_rejects_nonempty_target(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "history.db"
            with patch.object(database, "DB_PATH", str(source)), patch.dict(os.environ, {"RAG_DATABASE_URL": ""}):
                database.init_db()
                database.create_conversation("source-conv", "Copied")
                database.save_message("source-message", "source-conv", "user", "Hello")
                database.add_document("original.pdf", doc_id="source-doc", storage_name="source-doc.pdf")
            counts = migrate(source, self.url)
            self.assertEqual(counts["conversations"], 1)
            self.assertEqual(counts["documents"], 1)
            self.assertEqual(database.get_all_conversations()[0]["title"], "Copied")
            with self.assertRaises(ValueError):
                migrate(source, self.url)


if __name__ == "__main__":
    unittest.main()
