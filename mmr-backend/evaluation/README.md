# Phase 3 evaluation

The example JSONL files test the scorer only. They contain invented chunk IDs and **are not a measured project baseline**.

Create a private, fixed PDF corpus and ingest it into an isolated backend. Copy the resulting `chunk_id` values into a versioned case file with one object per line:

```json
{"id":"case-001","query":"What changed in the 2025 policy?","answerable":true,"relevant_chunk_ids":["document-id::2"]}
{"id":"case-002","query":"What is the policy on Mars?","answerable":false,"relevant_chunk_ids":[]}
```

Each case may include `sources`, a list of immutable document IDs to restrict retrieval in the non-streaming chat API. Omit it to search all indexed documents. This is useful for comparing like-for-like runs when an isolated corpus contains additional documents.

Include text, table, image, multi-turn, cross-document, and deliberately unsupported questions. Review the evidence manually before marking chunks relevant. Keep the corpus, indexed document IDs, case file, model configuration, and `k` fixed across runs. A new ingestion creates new document IDs, so remap the gold IDs before comparison. Do not commit private PDFs or answer content.

From `mmr-backend`, capture a baseline with the running API (this invokes the answer model and may incur API charges):

```bash
venv/bin/python -m scripts.capture_predictions --cases evaluation/cases.jsonl --output evaluation/baseline_predictions.jsonl --k 3
venv/bin/python -m scripts.evaluate --cases evaluation/cases.jsonl --predictions evaluation/baseline_predictions.jsonl --k 3 --output evaluation/baseline_report.json
```

The capture command only writes a complete run. The scorer requires one prediction per case. Add `groundedness` and `answer_quality` ratings in `[0, 1]` to each prediction after human review. Missing ratings remain `null` in the aggregate, with coverage counts; they are never inferred from retrieval scores. Groundedness asks whether every factual claim is supported by its cited evidence. Answer quality asks whether the answer addresses the question correctly and completely. Record the rating rubric and reviewers alongside the case set.

`retrieval_recall_at_k` is the mean fraction of each answerable question's gold chunks found in the first `k` results. `mean_reciprocal_rank_at_k` measures how early the first gold chunk appears. `citation_precision` is the share of unique cited chunk IDs that are both retrieved and labeled relevant; it does **not** prove claim-level support. `abstention_accuracy` measures whether the response abstains on unanswerable questions and answers answerable ones. Human groundedness and answer-quality ratings are reported separately. A null metric means there is no suitable denominator, not a zero score.

For a smoke test of the scorer, run it with `evaluation/example_cases.jsonl` and `evaluation/example_predictions.jsonl`. Do not compare that report against live results.
