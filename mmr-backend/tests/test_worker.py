import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import database
from tests import test_api  # installs the lightweight pipeline fixture before main import
from app import main, worker
from app import originals
from tests.test_originals import FakeS3


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_patch = patch.object(database, "DB_PATH", str(self.root / "jobs.db"))
        self.upload_patch = patch.object(main, "UPLOAD_DIR", str(self.root / "docs"))
        self.database_patch.start()
        self.upload_patch.start()
        Path(main.UPLOAD_DIR).mkdir()
        database.init_db()
        database.add_document("source.html", doc_id="source", storage_name="source.html", status="processing")
        (Path(main.UPLOAD_DIR) / "source.html").write_text("<p>Source</p>")
        self.job = database.enqueue_ingestion_job("source", "source.html", "source.html", "html", now=100)

    def tearDown(self):
        self.upload_patch.stop()
        self.database_patch.stop()
        self.temporary.cleanup()

    def test_worker_completes_and_marks_document_ready(self):
        chunk = SimpleNamespace(text="Source")
        document = SimpleNamespace(metadata={})
        with patch.object(main, "delete_document_vectors", return_value=True), \
                patch.object(main, "extract_sections", return_value=[chunk]), \
                patch.object(main, "build_documents", return_value=[document]), \
                patch.object(main, "store_documents") as store:
            self.assertTrue(worker.run_once(now=100))
        store.assert_called_once()
        self.assertEqual(document.metadata["source_format"], "html")
        self.assertEqual(database.get_ingestion_job(self.job["id"])["status"], "ready")
        self.assertEqual(database.get_document("source")["status"], "ready")

    def test_worker_reads_s3_original_without_shared_upload_volume(self):
        client = FakeS3()
        with patch.dict("os.environ", {"RAG_ORIGINALS_BUCKET": "test-bucket", "RAG_ORIGINALS_PREFIX": "sources"}), \
                patch.object(originals, "_client", return_value=client):
            source = Path(main.UPLOAD_DIR) / "source.html"
            originals.put("source.html", source)
            source.unlink()
            chunk = SimpleNamespace(text="Source")
            document = SimpleNamespace(metadata={})
            with patch.object(main, "delete_document_vectors", return_value=True), \
                    patch.object(main, "extract_sections", return_value=[chunk]), \
                    patch.object(main, "build_documents", return_value=[document]), \
                    patch.object(main, "store_documents"):
                self.assertTrue(worker.run_once(now=100))
            self.assertEqual(database.get_document("source")["status"], "ready")
            self.assertEqual(list(Path(main.UPLOAD_DIR).glob(".source-*")), [])

    def test_worker_failure_retries_then_dead_letters_without_losing_original(self):
        with patch.object(main, "delete_document_vectors", return_value=True), \
                patch.object(main, "extract_sections", side_effect=RuntimeError("private text")):
            for timestamp in (100, 111, 132):
                self.assertTrue(worker.run_once(now=timestamp))
        self.assertEqual(database.get_ingestion_job(self.job["id"])["status"], "dead")
        self.assertEqual(database.get_ingestion_job(self.job["id"])["error"], "RuntimeError")
        self.assertEqual(database.get_document("source")["status"], "failed")
        self.assertTrue((Path(main.UPLOAD_DIR) / "source.html").exists())
