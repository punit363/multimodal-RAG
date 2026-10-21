"""Bounded lexical ranking, reciprocal-rank fusion and diversity reranking."""

import math
import re
from collections import Counter
from typing import Any


STOPWORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is", "it", "of", "on", "or", "the", "to", "was", "were", "what", "when", "where", "which", "who", "why", "with"}


def tokenize(text: str) -> list[str]:
    """Extract meaningful case-insensitive terms for small-corpus BM25."""
    return [term for term in re.findall(r"[\w]+", text.casefold()) if term not in STOPWORDS]


def keyword_rank(query: str, texts: dict[str, str], limit: int = 20) -> list[tuple[str, float, float]]:
    """Rank candidate chunks by BM25 and return query-term coverage."""
    terms = set(tokenize(query))
    if not terms or not texts:
        return []
    tokenized = {chunk_id: tokenize(text) for chunk_id, text in texts.items()}
    average_length = sum(len(tokens) for tokens in tokenized.values()) / len(tokenized) or 1
    frequency = Counter(term for tokens in tokenized.values() for term in set(tokens))
    ranked = []
    for chunk_id, tokens in tokenized.items():
        counts = Counter(tokens)
        coverage = len(terms & counts.keys()) / len(terms)
        if coverage < 0.75:
            continue
        score = 0.0
        for term in terms:
            count = counts[term]
            if not count:
                continue
            idf = math.log(1 + (len(texts) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += idf * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * len(tokens) / average_length))
        if score > 0:
            ranked.append((chunk_id, score, coverage))
    return sorted(ranked, key=lambda item: (-item[1], item[0]))[:limit]


def reciprocal_rank_fusion(rankings: list[list[str]], limit: int = 30) -> list[str]:
    """Fuse ranked lists without treating incomparable scores as probabilities."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (60 + rank)
    return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:limit]


def rerank_diverse(ranked_ids: list[str], texts: dict[str, str], k: int) -> list[str]:
    """Greedily retain strong first-stage hits while reducing duplicate evidence."""
    remaining = ranked_ids[:]
    selected: list[str] = []
    terms = {chunk_id: set(tokenize(texts.get(chunk_id, ""))) for chunk_id in remaining}
    base = {chunk_id: 1 / (rank + 1) for rank, chunk_id in enumerate(remaining)}
    while remaining and len(selected) < k:
        def score(chunk_id: str) -> float:
            redundancy = max(
                (len(terms[chunk_id] & terms[chosen]) / len(terms[chunk_id] | terms[chosen])
                 if terms[chunk_id] | terms[chosen] else 0.0)
                for chosen in selected
            ) if selected else 0.0
            return 0.8 * base[chunk_id] - 0.2 * redundancy
        best = max(remaining, key=lambda chunk_id: (score(chunk_id), -ranked_ids.index(chunk_id)))
        selected.append(best)
        remaining.remove(best)
    return selected


def cosine_similarity(first: list[float], second: Any) -> float:
    """Normalize a stored embedding's cosine similarity to Chroma's score scale."""
    dot = sum(a * float(b) for a, b in zip(first, second))
    first_norm = math.sqrt(sum(a * a for a in first))
    second_norm = math.sqrt(sum(float(b) * float(b) for b in second))
    return dot / (first_norm * second_norm) if first_norm and second_norm else 0.0
