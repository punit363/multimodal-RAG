"""Bounded conversational query rewriting for retrieval only."""

import re
from collections.abc import Callable
from typing import Any


FOLLOWUP = re.compile(r"\b(it|its|they|their|them|this|that|these|those|same|previous|above)\b|\bwhat about\b|\bhow about\b", re.IGNORECASE)


def rewrite_followup_query(
    query: str,
    history: list[dict[str, Any]] | None,
    rewriter: Callable[[str], str],
) -> str:
    """Rewrite a dependent question with up to six prior turns, or preserve it."""
    turns = [
        (message.get("role"), str(message.get("content", ""))[:500].strip())
        for message in (history or [])[-6:]
        if message.get("role") in {"user", "assistant"} and message.get("content")
    ]
    prior_questions = [content for role, content in turns if role == "user"]
    if not prior_questions or not FOLLOWUP.search(query):
        return query
    context = "\n".join(f"{role}: {content}" for role, content in turns)
    prompt = (
        "Rewrite the final user question into one standalone search query using only the conversation context. "
        "Preserve names, dates and document references; do not answer the question or add new facts. "
        "Return only the search query, at most 100 words.\n\n"
        f"Conversation:\n{context}\nuser: {query[:500]}"
    )
    try:
        rewritten = rewriter(prompt).strip().strip('"')
    except Exception:
        rewritten = ""
    if not rewritten or len(rewritten) > 500 or "[[source:" in rewritten:
        return f"{prior_questions[-1]} {query}"[:500]
    return rewritten
