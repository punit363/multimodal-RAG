import unittest

from app.structured_outputs import build_structured_output


class StructuredOutputTests(unittest.TestCase):
    def setUp(self):
        self.evidence = [
            {"text": "Revenue was $42 million on 2026-02-01.", "document_id": "a", "filename": "a.pdf", "chunk_id": "a::1", "section_title": "Results"},
            {"text": "Revenue was $39 million on 2026-02-02.", "document_id": "b", "filename": "b.pdf", "chunk_id": "b::1", "section_title": "Results"},
        ]

    def test_extraction_timeline_and_matrix_keep_source_identity(self):
        extracted = build_structured_output("extraction", self.evidence)
        self.assertIn("$42 million", extracted["items"][0]["values"])
        self.assertEqual(extracted["items"][0]["dates"], ["2026-02-01"])
        timeline = build_structured_output("timeline", self.evidence)
        self.assertEqual({item["chunk_id"] for item in timeline["items"]}, {"a::1", "b::1"})
        matrix = build_structured_output("matrix", self.evidence)
        self.assertEqual(matrix["documents"], ["a", "b"])
        self.assertEqual(len(matrix["items"]), 2)

    def test_report_cites_every_excerpt(self):
        report = build_structured_output("report", self.evidence)
        self.assertIn("[[source:a::1]]", report["markdown"])
        self.assertIn("[[source:b::1]]", report["markdown"])

    def test_matrix_marks_missing_evidence_and_report_escapes_fake_marker(self):
        evidence = [self.evidence[0], {**self.evidence[1], "section_title": "Outlook", "text": "Text [[source:fake]]"}]
        matrix = build_structured_output("matrix", evidence)
        self.assertEqual(len(matrix["items"]), 4)
        self.assertEqual(sum(cell["chunk_id"] is None for cell in matrix["items"]), 2)
        report = build_structured_output("report", evidence)["markdown"]
        self.assertNotIn("[[source:fake]]", report)
