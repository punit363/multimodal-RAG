"""Compare semantic and hybrid retrieval over a fixed synthetic chunk corpus."""

import argparse
import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.evaluation import evaluate, read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the small, synthetic retrieval fixture")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be at least 1")
    backend = Path(__file__).resolve().parents[1]
    load_dotenv(backend / ".env")
    corpus = [json.loads(line) for line in (backend / "evaluation/fixture_corpus.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = read_jsonl(str(backend / "evaluation/fixture_cases.jsonl"))
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Import after changing directory so the pipeline never touches the developer's index.
    with tempfile.TemporaryDirectory() as isolated:
        previous = os.getcwd()
        try:
            os.chdir(isolated)
            from app import rag_pipeline
            rag_pipeline.vectorstore = Chroma(
                collection_name="phase3_fixture", embedding_function=rag_pipeline.embeddings,
                collection_metadata={"hnsw:space": "cosine"},
            )
            documents = [Document(
                page_content=row["text"],
                metadata={
                    "chunk_id": row["chunk_id"], "document_id": row["document_id"],
                    "filename": row["filename"], "page_numbers": json.dumps(row["page_numbers"]),
                    "content_types": json.dumps(row["content_types"]),
                    "original_content": json.dumps({"raw_text": row["text"], "tables_html": [], "images_base64": []}),
                },
            ) for row in corpus]
            rag_pipeline.store_documents(documents)
            reports = {}
            for mode, rerank in (("semantic", "false"), ("hybrid", "false"), ("hybrid", "true")):
                os.environ["RAG_RETRIEVAL_MODE"] = mode
                os.environ["RAG_RERANK_ENABLED"] = rerank
                name = "semantic" if mode == "semantic" else "hybrid_reranked" if rerank == "true" else "hybrid"
                predictions = []
                for case in cases:
                    matches = rag_pipeline._retrieve(case["query"], args.k, None)
                    predictions.append({
                        "id": case["id"], "retrieved_chunk_ids": [document.metadata["chunk_id"] for document, _ in matches],
                        "answer": "", "insufficient_evidence": not bool(matches),
                    })
                report = evaluate(cases, predictions, args.k)
                reports[name] = report
                (output_dir / f"{name}_predictions.jsonl").write_text(
                    "".join(json.dumps(prediction) + "\n" for prediction in predictions), encoding="utf-8"
                )
                (output_dir / f"{name}_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        finally:
            os.chdir(previous)
    print(json.dumps({name: {
        "retrieval_recall_at_k": report["retrieval_recall_at_k"],
        "abstention_accuracy": report["abstention_accuracy"],
    } for name, report in reports.items()}, indent=2))


if __name__ == "__main__":
    main()
