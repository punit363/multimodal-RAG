"""Offline, annotation-aware quality metrics for fixed RAG evaluation sets."""

import json
import math
import re
from pathlib import Path
from typing import Any


CITATION_PATTERN = re.compile(r"\[\[source:([^\]]+)\]\]")


def read_jsonl(path: str) -> list[dict[str, Any]]:
    """Read uniquely identified JSONL records without accepting partial data."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
            raise ValueError(f"{path}:{line_number}: expected an object with a non-empty id")
        if record["id"] in seen:
            raise ValueError(f"{path}:{line_number}: duplicate id {record['id']}")
        seen.add(record["id"])
        records.append(record)
    if not records:
        raise ValueError(f"{path}: no records")
    return records


def _chunk_ids(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label} must be a list of non-empty chunk IDs")
    return value


def _rating(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{label} must be a number between 0 and 1")
    return float(value)


def evaluate(cases: list[dict[str, Any]], predictions: list[dict[str, Any]], k: int = 3) -> dict[str, Any]:
    """Score retrieval and citations; aggregate explicitly supplied human ratings."""
    if k < 1:
        raise ValueError("k must be at least 1")
    by_id = {prediction["id"]: prediction for prediction in predictions}
    case_ids = {case["id"] for case in cases}
    if len(case_ids) != len(cases) or len(by_id) != len(predictions) or set(by_id) != case_ids:
        raise ValueError("predictions must have exactly one record for every case id")

    hits: list[float] = []
    reciprocal_ranks: list[float] = []
    citation_correct = 0
    citation_total = 0
    abstention_correct = 0
    groundedness: list[float] = []
    answer_quality: list[float] = []
    rows: list[dict[str, Any]] = []

    for case in cases:
        case_id = case["id"]
        prediction = by_id[case_id]
        relevant = set(_chunk_ids(case.get("relevant_chunk_ids"), f"{case_id}.relevant_chunk_ids"))
        answerable = case.get("answerable")
        if not isinstance(answerable, bool) or answerable != bool(relevant):
            raise ValueError(f"{case_id}: answerable must match whether relevant_chunk_ids is non-empty")
        retrieved = _chunk_ids(prediction.get("retrieved_chunk_ids"), f"{case_id}.retrieved_chunk_ids")
        answer = prediction.get("answer", "")
        if not isinstance(answer, str):
            raise ValueError(f"{case_id}.answer must be a string")
        cited = list(dict.fromkeys(CITATION_PATTERN.findall(answer)))
        abstained = prediction.get("insufficient_evidence")
        if not isinstance(abstained, bool):
            raise ValueError(f"{case_id}.insufficient_evidence must be a boolean")
        grounded = _rating(prediction.get("groundedness"), f"{case_id}.groundedness")
        quality = _rating(prediction.get("answer_quality"), f"{case_id}.answer_quality")
        if grounded is not None:
            groundedness.append(grounded)
        if quality is not None:
            answer_quality.append(quality)

        top = retrieved[:k]
        rank = next((index + 1 for index, chunk_id in enumerate(top) if chunk_id in relevant), None)
        if answerable:
            hits.append(len(set(top) & relevant) / len(relevant))
            reciprocal_ranks.append(1 / rank if rank else 0.0)
        correct_citations = sum(chunk_id in relevant and chunk_id in retrieved for chunk_id in cited)
        citation_correct += correct_citations
        citation_total += len(cited)
        abstention_correct += abstained == (not answerable)
        rows.append({
            "id": case_id,
            "retrieval_hit_at_k": rank is not None if answerable else None,
            "retrieval_recall_at_k": len(set(top) & relevant) / len(relevant) if answerable else None,
            "first_relevant_rank": rank,
            "citation_correct": correct_citations,
            "citation_count": len(cited),
            "abstention_correct": abstained == (not answerable),
        })

    return {
        "cases": len(cases),
        "answerable_cases": len(hits),
        "k": k,
        "retrieval_recall_at_k": sum(hits) / len(hits) if hits else None,
        "mean_reciprocal_rank_at_k": sum(reciprocal_ranks) / len(reciprocal_ranks) if hits else None,
        "citation_precision": citation_correct / citation_total if citation_total else None,
        "citation_count": citation_total,
        "abstention_accuracy": abstention_correct / len(cases),
        "groundedness_mean": sum(groundedness) / len(groundedness) if groundedness else None,
        "groundedness_rated_cases": len(groundedness),
        "answer_quality_mean": sum(answer_quality) / len(answer_quality) if answer_quality else None,
        "answer_quality_rated_cases": len(answer_quality),
        "per_case": rows,
    }
