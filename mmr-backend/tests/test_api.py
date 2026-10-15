import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database


fake_rag_pipeline = types.ModuleType("app.rag_pipeline")
fake_rag_pipeline.partition_documents = lambda path: []
fake_rag_pipeline.create_chunks_by_title = lambda elements: []
fake_rag_pipeline.build_documents = lambda chunks, filename: []
fake_rag_pipeline.store_documents = lambda documents: None
fake_rag_pipeline.answer_query = lambda query, k=3: {"answer": "stub", "sources": []}
fake_rag_pipeline.answer_query_stream = lambda query, k=3, sources=None: iter(())
fake_rag_pipeline.delete_document_vectors = lambda filename: True
sys.modules["app.rag_pipeline"] = fake_rag_pipeline

from app import main  # noqa: E402


class ApiTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self._temporary_directory.name)
        self._database_patch = patch.object(database, "DB_PATH", str(root / "api.db"))
        self._upload_patch = patch.object(main, "UPLOAD_DIR", str(root / "docs"))
        self._database_patch.start()
        self._upload_patch.start()
        Path(main.UPLOAD_DIR).mkdir()
        database.init_db()
        self._client_context = TestClient(main.app)
        self.client = self._client_context.__enter__()

    def tearDown(self):
        self._client_context.__exit__(None, None, None)
        self._upload_patch.stop()
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

    def test_document_delete_removes_registry_vectors_and_file(self):
        document = database.add_document("report.pdf")
        uploaded_file = Path(main.UPLOAD_DIR) / "report.pdf"
        uploaded_file.write_bytes(b"%PDF-test")

        with patch.object(main, "delete_document_vectors", return_value=True) as delete_vectors:
            response = self.client.delete(f"/api/documents/{document['id']}")

        self.assertEqual(response.status_code, 200)
        delete_vectors.assert_called_once_with("report.pdf")
        self.assertFalse(uploaded_file.exists())
        self.assertEqual(database.list_documents(), [])

    def test_ingestion_rejects_non_pdf_files(self):
        response = self.client.post(
            "/api/ingest-stream",
            files={"file": ("notes.txt", b"not a pdf", "text/plain")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Only PDF files are supported.")


if __name__ == "__main__":
    unittest.main()
