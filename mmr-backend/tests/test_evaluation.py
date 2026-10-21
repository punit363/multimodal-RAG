import json
import tempfile
import unittest
from pathlib import Path

from app.evaluation import evaluate, read_jsonl


class EvaluationTests(unittest.TestCase):
    def test_metrics_include_retrieval_citations_abstention_and_rated_coverage(self):
        cases = [
            {"id": "answerable", "answerable": True, "relevant_chunk_ids": ["doc::2"]},
            {"id": "unsupported", "answerable": False, "relevant_chunk_ids": []},
        ]
        predictions = [
            {
                "id": "answerable", "retrieved_chunk_ids": ["wrong::0", "doc::2"],
                "answer": "Fact [[source:doc::2]] and error [[source:wrong::0]]",
                "insufficient_evidence": False, "groundedness": 0.5, "answer_quality": 1,
            },
            {"id": "unsupported", "retrieved_chunk_ids": [], "answer": "No evidence", "insufficient_evidence": True},
        ]
        report = evaluate(cases, predictions, k=2)
        self.assertEqual(report["retrieval_recall_at_k"], 1)
        self.assertEqual(report["mean_reciprocal_rank_at_k"], 0.5)
        self.assertEqual(report["citation_precision"], 0.5)
        self.assertEqual(report["abstention_accuracy"], 1)
        self.assertEqual(report["groundedness_mean"], 0.5)
        self.assertEqual(report["groundedness_rated_cases"], 1)
        self.assertEqual(report["answer_quality_rated_cases"], 1)

    def test_missing_predictions_and_invalid_annotations_fail(self):
        cases = [{"id": "one", "answerable": True, "relevant_chunk_ids": ["doc::0"]}]
        with self.assertRaisesRegex(ValueError, "exactly one"):
            evaluate(cases, [])
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            evaluate(cases, [{"id": "one", "retrieved_chunk_ids": [], "answer": "", "insufficient_evidence": True, "groundedness": 2}])

    def test_read_jsonl_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text(json.dumps({"id": "same"}) + "\n" + json.dumps({"id": "same"}) + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate id"):
                read_jsonl(str(path))


if __name__ == "__main__":
    unittest.main()
