import unittest

from app.ranking import keyword_rank, reciprocal_rank_fusion, rerank_diverse


class RankingTests(unittest.TestCase):
    def test_keyword_rank_recovers_exact_terms_missed_by_semantic_order(self):
        ranked = keyword_rank(
            "quarterly revenue 2026",
            {
                "unrelated": "Quarterly revenue in a different period",
                "target": "The quarterly revenue for 2026 was 12 million",
                "noise": "A project timeline and staffing plan",
            },
        )
        self.assertEqual(ranked[0][0], "target")
        self.assertEqual(ranked[0][2], 1.0)
        self.assertNotIn("noise", [item[0] for item in ranked])

    def test_fusion_rewards_overlap_and_reranker_reduces_duplicates(self):
        fused = reciprocal_rank_fusion([["first", "shared"], ["shared", "second"]])
        self.assertEqual(fused[0], "shared")
        diverse = rerank_diverse(
            ["first", "duplicate", "different"],
            {
                "first": "revenue quarterly 2026 increased strongly",
                "duplicate": "revenue quarterly 2026 increased strongly",
                "different": "expenses declined after restructuring",
            },
            2,
        )
        self.assertEqual(diverse, ["first", "different"])


if __name__ == "__main__":
    unittest.main()
