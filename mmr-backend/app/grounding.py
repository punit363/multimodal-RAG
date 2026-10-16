"""Relevance gate shared by streamed and non-streamed answers."""

import math
import os
from typing import Any, List, Tuple


INSUFFICIENT_EVIDENCE_ANSWER = (
    "I don't have enough relevant evidence in the selected documents to answer that question."
)


def minimum_relevance_score() -> float:
    value = float(os.getenv("RAG_MIN_RELEVANCE_SCORE", "0.35"))
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("RAG_MIN_RELEVANCE_SCORE must be between 0 and 1.")
    return value


def supported_results(results: List[Tuple[Any, float]]) -> List[Tuple[Any, float]]:
    """Keep only valid, sufficiently relevant Chroma cosine relevance scores."""
    threshold = minimum_relevance_score()
    return [
        (document, score)
        for document, score in results
        if isinstance(score, (int, float))
        and math.isfinite(score)
        and 0 <= score <= 1
        and score >= threshold
    ]
