"""Score a fixed evaluation set against captured predictions.

Run from mmr-backend: python -m scripts.evaluate --cases path --predictions path
"""

import argparse
import json

from app.evaluation import evaluate, read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a fixed MultiModal RAG evaluation set")
    parser.add_argument("--cases", required=True, help="JSONL gold cases")
    parser.add_argument("--predictions", required=True, help="JSONL answer/retrieval records")
    parser.add_argument("--k", type=int, default=3, help="retrieval cutoff (default: 3)")
    parser.add_argument("--output", help="optional path for the JSON report")
    args = parser.parse_args()

    report = evaluate(read_jsonl(args.cases), read_jsonl(args.predictions), args.k)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            output.write(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
