import json
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app import database


fake_rag_pipeline = types.ModuleType("app.rag_pipeline")
fake_rag_pipeline.partition_documents = lambda path: []
fake_rag_pipeline.create_chunks_by_title = lambda elements: []
fake_rag_pipeline.build_documents = lambda chunks, filename, document_id=None: []
fake_rag_pipeline.store_documents = lambda documents: None
fake_rag_pipeline.answer_query = lambda query, k=3, sources=None: {"answer": "stub", "sources": []}
fake_rag_pipeline.answer_query_stream = lambda query, k=3, sources=None: iter(())
fake_rag_pipeline.delete_document_vectors = lambda filename: True
sys.modules["app.rag_pipeline"] = fake_rag_pipeline

from app import main  # noqa: E402
from app.security import sanitize_table_html  # noqa: E402


class ApiTests(unittest.TestCase):
    @staticmethod
    def pdf_bytes(page_count=1):
        output = io.BytesIO()
        writer = PdfWriter()
        for _ in range(page_count):
            writer.add_blank_page(width=612, height=792)
        writer.write(output)
        return output.getvalue()

    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self._temporary_directory.name)
        self._database_patch = patch.object(database, "DB_PATH", str(root / "api.db"))
        self._upload_patch = patch.object(main, "UPLOAD_DIR", str(root / "docs"))
        self._quarantine_patch = patch.object(
            main, "QUARANTINE_DIR", str(root / "docs" / ".quarantine")
        )
        self._database_patch.start()
        self._upload_patch.start()
        self._quarantine_patch.start()
        Path(main.QUARANTINE_DIR).mkdir(parents=True)
        database.init_db()
        self._client_context = TestClient(main.app)
        self.client = self._client_context.__enter__()

    def tearDown(self):
        self._client_context.__exit__(None, None, None)
        self._upload_patch.stop()
        self._quarantine_patch.stop()
        self._database_patch.stop()
        self._temporary_directory.cleanup()

    def test_health_and_conversation_round_trip(self):
        health = self.client.get("/")
        created = self.client.post("/api/conversations", json={"title": "Quarterly review"})
        conversations = self.client.get("/api/conversations")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(conversations.json()[0]["title"], "Quarterly review")

    def test_chat_stream_forwards_selected_sources_and_persists_messages(self):
        captured = {}
        source = {"filename": "report.pdf", "chunk_id": 1}

        def stream(query, k=3, sources=None):
            captured.update({"query": query, "k": k, "sources": sources})
            yield f"data: {json.dumps({'type': 'sources', 'sources': [source]})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'token': 'Grounded answer'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        with patch.object(main, "answer_query_stream", stream):
            response = self.client.post(
                "/api/chat-stream",
                json={
                    "query": "What changed?",
                    "conversation_id": "conversation-1",
                    "user_message_id": "user-1",
                    "assistant_message_id": "assistant-1",
                    "top_k": 5,
                    "sources": ["report.pdf"],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            captured,
            {"query": "What changed?", "k": 5, "sources": ["report.pdf"]},
        )
        messages = self.client.get("/api/conversations").json()[0]["messages"]
        self.assertEqual(messages[0]["content"], "What changed?")
        self.assertEqual(messages[1]["content"], "Grounded answer")
        self.assertEqual(messages[1]["sources"], [source])

    def test_non_stream_chat_forwards_document_filter(self):
        captured = {}

        def answer(query, k=3, sources=None):
            captured.update({"query": query, "k": k, "sources": sources})
            return {"answer": "filtered", "sources": []}

        with patch.object(main, "answer_query", answer):
            response = self.client.post(
                "/api/chat",
                json={"query": "What changed?", "top_k": 5, "sources": ["document-1"]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured, {"query": "What changed?", "k": 5, "sources": ["document-1"]})

    def test_chat_stream_persists_a_retryable_failure_message(self):
        def stream(query, k=3, sources=None):
            yield f"data: {json.dumps({'type': 'error', 'message': 'model unavailable'})}\n\n"

        with patch.object(main, "answer_query_stream", stream):
            response = self.client.post(
                "/api/chat-stream",
                json={
                    "query": "What changed?",
                    "conversation_id": "conversation-error",
                    "user_message_id": "user-error",
                    "assistant_message_id": "assistant-error",
                    "sources": ["document-1"],
                },
            )

        self.assertEqual(response.status_code, 200)
        messages = self.client.get("/api/conversations").json()[0]["messages"]
        self.assertEqual(messages[1]["content"], "Answer failed: model unavailable")

    def test_feedback_api_persists_and_rejects_invalid_targets(self):
        database.create_conversation("conversation-1", "Test")
        database.save_message("assistant-1", "conversation-1", "assistant", "Answer")
        response = self.client.patch("/api/messages/assistant-1/feedback", json={"feedback": "helpful"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/conversations").json()[0]["messages"][0]["feedback"], "helpful")
        self.assertEqual(self.client.patch("/api/messages/missing/feedback", json={"feedback": "helpful"}).status_code, 404)
        self.assertEqual(self.client.patch("/api/messages/assistant-1/feedback", json={"feedback": "maybe"}).status_code, 422)

    def test_document_delete_removes_registry_vectors_and_file(self):
        document = database.add_document(
            "report.pdf", doc_id="document-1", storage_name="document-1.pdf"
        )
        uploaded_file = Path(main.UPLOAD_DIR) / "document-1.pdf"
        uploaded_file.write_bytes(self.pdf_bytes())

        with patch.object(main, "delete_document_vectors", return_value=True) as delete_vectors:
            response = self.client.delete(f"/api/documents/{document['id']}")

        self.assertEqual(response.status_code, 200)
        delete_vectors.assert_called_once_with("document-1")
        self.assertFalse(uploaded_file.exists())
        self.assertEqual(database.list_documents(), [])

    def test_pdf_endpoint_serves_only_registered_ready_documents(self):
        document = database.add_document(
            "report.pdf", doc_id="document-pdf", storage_name="document-pdf.pdf"
        )
        payload = self.pdf_bytes(2)
        (Path(main.UPLOAD_DIR) / "document-pdf.pdf").write_bytes(payload)

        response = self.client.get(f"/api/documents/{document['id']}/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, payload)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("inline", response.headers["content-disposition"])
        self.assertEqual(self.client.get("/api/documents/missing/pdf").status_code, 404)

        database.update_document_status(document["id"], "failed")
        self.assertEqual(
            self.client.get(f"/api/documents/{document['id']}/pdf").status_code, 404
        )

    def test_ingestion_rejects_non_pdf_files(self):
        response = self.client.post(
            "/api/ingest-stream",
            files={"file": ("notes.txt", b"not a pdf", "text/plain")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Only PDF files are supported.")

    def test_ingestion_rejects_wrong_mime_signature_and_oversized_files(self):
        wrong_mime = self.client.post(
            "/api/ingest-stream",
            files={"file": ("report.pdf", self.pdf_bytes(), "text/plain")},
        )
        bad_signature = self.client.post(
            "/api/ingest-stream",
            files={"file": ("report.pdf", b"not-a-pdf", "application/pdf")},
        )
        with patch.object(main, "MAX_UPLOAD_BYTES", 8):
            oversized = self.client.post(
                "/api/ingest-stream",
                files={"file": ("report.pdf", self.pdf_bytes(), "application/pdf")},
            )
        with patch.object(main, "MAX_PDF_PAGES", 1):
            too_many_pages = self.client.post(
                "/api/ingest-stream",
                files={"file": ("report.pdf", self.pdf_bytes(2), "application/pdf")},
            )

        self.assertEqual(wrong_mime.status_code, 400)
        self.assertIn("MIME", wrong_mime.json()["detail"])
        self.assertEqual(bad_signature.status_code, 400)
        self.assertIn("signature", bad_signature.json()["detail"])
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(too_many_pages.status_code, 400)
        self.assertIn("between 1 and 1 pages", too_many_pages.json()["detail"])
        self.assertEqual(list(Path(main.UPLOAD_DIR).glob("*.pdf")), [])

    def test_duplicate_filenames_get_distinct_ids_and_storage_paths(self):
        payload = self.pdf_bytes()
        first = self.client.post(
            "/api/ingest-stream",
            files={"file": ("report.pdf", payload, "application/pdf")},
        )
        second = self.client.post(
            "/api/ingest-stream",
            files={"file": ("report.pdf", payload, "application/pdf")},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        documents = database.list_documents()
        self.assertEqual(len(documents), 2)
        self.assertEqual({doc["filename"] for doc in documents}, {"report.pdf"})
        self.assertEqual(len({doc["id"] for doc in documents}), 2)
        self.assertEqual(len({doc["storage_name"] for doc in documents}), 2)
        for document in documents:
            self.assertTrue((Path(main.UPLOAD_DIR) / document["storage_name"]).exists())

    def test_failed_ingestion_removes_partial_file_registry_and_vectors(self):
        with (
            patch.object(main, "partition_documents", side_effect=RuntimeError("partition failed")),
            patch.object(main, "delete_document_vectors", return_value=True) as delete_vectors,
        ):
            response = self.client.post(
                "/api/ingest-stream",
                files={"file": ("report.pdf", self.pdf_bytes(), "application/pdf")},
            )

        self.assertIn('"status": "error"', response.text)
        self.assertEqual(database.list_documents(), [])
        self.assertEqual(list(Path(main.UPLOAD_DIR).glob("*.pdf")), [])
        delete_vectors.assert_called_once()

    def test_delete_failure_preserves_retryable_registry_and_file(self):
        document = database.add_document(
            "report.pdf", doc_id="document-2", storage_name="document-2.pdf"
        )
        uploaded_file = Path(main.UPLOAD_DIR) / "document-2.pdf"
        uploaded_file.write_bytes(self.pdf_bytes())

        with patch.object(main, "delete_document_vectors", side_effect=RuntimeError("busy")):
            response = self.client.delete(f"/api/documents/{document['id']}")

        preserved = database.get_document(document["id"])
        self.assertEqual(response.status_code, 500)
        self.assertEqual(preserved["status"], "deletion_failed")
        self.assertTrue(uploaded_file.exists())

    def test_table_html_sanitizer_removes_active_content(self):
        unsafe = '<table onclick="alert(1)"><tr><td>Safe<script>alert(2)</script></td></tr></table>'
        cleaned = sanitize_table_html(unsafe)

        self.assertIn("<table>", cleaned)
        self.assertIn("Safe", cleaned)
        self.assertNotIn("script", cleaned.lower())
        self.assertNotIn("onclick", cleaned.lower())


if __name__ == "__main__":
    unittest.main()
