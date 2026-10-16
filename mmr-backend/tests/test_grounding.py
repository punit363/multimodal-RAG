import os
import types
import unittest
from unittest.mock import patch

from app.grounding import supported_results
from app.source_metadata import source_location


def element(page, points=None, width=100, height=200):
    coordinates = None
    if points is not None:
        pixel_space = type("PixelSpace", (), {"width": width, "height": height})()
        coordinates = types.SimpleNamespace(system=pixel_space, points=points)
    return types.SimpleNamespace(
        metadata=types.SimpleNamespace(page_number=page, coordinates=coordinates)
    )


class GroundingTests(unittest.TestCase):
    def test_relevance_gate_rejects_weak_and_invalid_scores(self):
        results = [("weak", 0.34), ("supported", 0.7), ("invalid", float("nan"))]
        with patch.dict(os.environ, {"RAG_MIN_RELEVANCE_SCORE": "0.35"}):
            self.assertEqual(supported_results(results), [("supported", 0.7)])

    def test_source_location_preserves_page_and_reliable_rectangle(self):
        chunk = types.SimpleNamespace(
            metadata=types.SimpleNamespace(
                orig_elements=[
                    element(2, [(10, 20), (30, 20), (30, 40), (10, 40)]),
                    element(2, [(20, 40), (40, 40), (40, 60), (20, 60)]),
                ]
            )
        )
        location = source_location(chunk)
        self.assertEqual(location["page_numbers"], [2])
        for key, value in {"left": 0.1, "top": 0.1, "width": 0.3, "height": 0.2}.items():
            self.assertAlmostEqual(location["highlight_rect"][key], value)

    def test_source_location_uses_page_fallback_without_reliable_rectangle(self):
        chunk = types.SimpleNamespace(
            metadata=types.SimpleNamespace(
                orig_elements=[element(2), element(3)]
            )
        )
        self.assertEqual(
            source_location(chunk), {"page_numbers": [2, 3], "highlight_rect": None}
        )


if __name__ == "__main__":
    unittest.main()
