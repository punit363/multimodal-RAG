import unittest

from app.query_rewrite import rewrite_followup_query


class QueryRewriteTests(unittest.TestCase):
    def test_standalone_question_does_not_call_rewriter(self):
        self.assertEqual(
            rewrite_followup_query("What is the 2026 revenue?", [{"role": "user", "content": "Earlier topic"}], lambda prompt: self.fail("unexpected rewrite")),
            "What is the 2026 revenue?",
        )

    def test_followup_uses_bounded_history(self):
        history = [{"role": "user", "content": "What is the revenue in the annual report?"}]
        seen = []
        result = rewrite_followup_query("What about 2026?", history, lambda prompt: seen.append(prompt) or "What is the 2026 revenue in the annual report?")
        self.assertEqual(result, "What is the 2026 revenue in the annual report?")
        self.assertIn("annual report", seen[0])

    def test_rewrite_failure_falls_back_to_prior_question(self):
        result = rewrite_followup_query(
            "What about it?", [{"role": "user", "content": "Summarize the budget"}],
            lambda prompt: "[[source:invented]]",
        )
        self.assertEqual(result, "Summarize the budget What about it?")


if __name__ == "__main__":
    unittest.main()
