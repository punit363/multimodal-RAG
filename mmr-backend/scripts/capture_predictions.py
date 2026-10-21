"""Capture answers and ranked sources from the running non-streaming chat API."""

import argparse
import json
from urllib.request import Request, urlopen

from app.evaluation import read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture RAG predictions for a fixed case set")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--api-base-url", default="http://localhost:8000")
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be at least 1")
    cases = read_jsonl(args.cases)
    url = f"{args.api_base_url.rstrip('/')}/api/chat"

    # Collect all responses before writing, so failed runs cannot masquerade as a full baseline.
    predictions = []
    for case in cases:
        request = Request(
            url,
            data=json.dumps({
                "query": case["query"],
                "top_k": args.k,
                "sources": case.get("sources"),
                "filters": case.get("filters"),
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
        predictions.append({
            "id": case["id"],
            "retrieved_chunk_ids": [source["chunk_id"] for source in result.get("sources", [])],
            "answer": result["answer"],
            "insufficient_evidence": result.get("insufficient_evidence", False),
        })
    with open(args.output, "w", encoding="utf-8") as output:
        for prediction in predictions:
            output.write(json.dumps(prediction) + "\n")


if __name__ == "__main__":
    main()
