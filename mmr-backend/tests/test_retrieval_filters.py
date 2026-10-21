import unittest

from pydantic import ValidationError

from app.retrieval_filters import RetrievalFilters, eligible_chunk_ids


class RetrievalFilterTests(unittest.TestCase):
    def test_combined_filters_keep_only_matching_explicit_metadata(self):
        filters = RetrievalFilters(
            pages=[3], content_types=["table"], created_from="2026-01-01",
            created_to="2026-12-31", tags=["Finance"],
        )
        ids = ["doc-1::0", "doc-1::1", "doc-2::0", "legacy::0"]
        metadatas = [
            {"document_id": "doc-1", "page_numbers": "[3]", "content_types": '["text", "table"]'},
            {"document_id": "doc-1", "page_numbers": "[4]", "content_types": '["text", "table"]'},
            {"document_id": "doc-2", "page_numbers": "[3]", "content_types": '["text", "table"]'},
            {"document_id": "legacy"},
        ]
        documents = [
            {"id": "doc-1", "filename": "first.pdf", "storage_name": "doc-1.pdf", "status": "ready", "created_at": "2026-06-01 09:00:00", "tags": ["finance"]},
            {"id": "doc-2", "filename": "second.pdf", "storage_name": "doc-2.pdf", "status": "ready", "created_at": "2026-06-01 09:00:00", "tags": []},
        ]
        self.assertEqual(eligible_chunk_ids(ids, metadatas, documents, filters), ["doc-1::0"])

    def test_missing_metadata_does_not_pass_a_requested_filter(self):
        self.assertEqual(
            eligible_chunk_ids(["legacy::0"], [{"document_id": "legacy"}], [], RetrievalFilters(pages=[1])),
            [],
        )

    def test_invalid_scope_is_rejected(self):
        for scope in ({"pages": [0]}, {"content_types": ["audio"]}, {"created_from": "2026-12-31", "created_to": "2026-01-01"}):
            with self.subTest(scope=scope), self.assertRaises(ValidationError):
                RetrievalFilters(**scope)


if __name__ == "__main__":
    unittest.main()
