"""Deterministic, source-linked outputs from indexed evidence."""

import re
from collections import defaultdict
from typing import Any

DATE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b", re.I)
NUMBER = re.compile(r"(?<!\w)(?:[$€£₹]\s*)?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|million|billion|crore|lakh)?\b", re.I)


def _sentences(text: str) -> list[str]:
    return [" ".join(part.split())[:320] for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _markdown_text(value: str) -> str:
    return " ".join(value.split()).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def build_structured_output(kind: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce facts, chronology, matrix, or Markdown with citations to supplied chunks."""
    if kind not in {"extraction", "timeline", "matrix", "report"}:
        raise ValueError("Unsupported output type.")
    if not evidence:
        return {"kind": kind, "items": [], "markdown": "No indexed evidence was available."}
    rows = []
    for source in evidence:
        for sentence in _sentences(source["text"]):
            rows.append({"text": sentence, "document_id": source["document_id"],
                         "filename": source["filename"], "chunk_id": source["chunk_id"],
                         "section_title": source.get("section_title") or "Untitled section"})
    rows = rows[:200]
    if kind == "extraction":
        items = []
        for row in rows:
            dates = DATE.findall(row["text"])
            numbers = NUMBER.findall(DATE.sub(" ", row["text"]))
            if dates or numbers:
                items.append({**row, "dates": dates[:5], "values": numbers[:8]})
        return {"kind": kind, "items": items[:50]}
    if kind == "timeline":
        items = [{**row, "date": date} for row in rows for date in DATE.findall(row["text"])]
        return {"kind": kind, "items": sorted(items, key=lambda item: item["date"])[:50]}
    if kind == "matrix":
        documents = list(dict.fromkeys(row["document_id"] for row in rows))
        sections = list(dict.fromkeys(row["section_title"] for row in rows))[:20]
        cells = []
        for section in sections:
            for document_id in documents:
                match = next((row for row in rows if row["section_title"] == section and row["document_id"] == document_id), None)
                cells.append({"section": section, "document_id": document_id,
                              "text": match["text"] if match else "Unavailable in indexed evidence",
                              "chunk_id": match["chunk_id"] if match else None})
        return {"kind": kind, "documents": documents, "sections": sections, "items": cells}
    groups = defaultdict(list)
    for row in rows:
        if len(groups[row["document_id"]]) < 5:
            groups[row["document_id"]].append(row)
    lines = ["# Source-backed report", "", "This report contains extractive excerpts from indexed sources.", ""]
    items = []
    for document_id, entries in groups.items():
        lines.append(f"## {_markdown_text(entries[0]['filename'])}")
        lines.append("")
        for entry in entries:
            excerpt = _markdown_text(entry["text"].replace("[[source:", "[source:"))
            lines.append(f"- {excerpt} [[source:{entry['chunk_id']}]]")
            items.append(entry)
        lines.append("")
    lines.append("## Source index")
    lines.extend(f"- [[source:{entry['chunk_id']}]] — {_markdown_text(entry['filename'])} / {_markdown_text(entry['section_title'])}" for entry in items)
    return {"kind": kind, "items": items, "markdown": "\n".join(lines) + "\n"}
