# Phase 3 evaluation

The example JSONL files test the scorer only. They contain invented chunk IDs and **are not a measured project baseline**.

Create a private, fixed PDF corpus and ingest it into an isolated backend. Copy the resulting `chunk_id` values into a versioned case file with one object per line:

```json
{"id":"case-001","query":"What changed in the 2025 policy?","answerable":true,"relevant_chunk_ids":["document-id::2"]}
{"id":"case-002","query":"What is the policy on Mars?","answerable":false,"relevant_chunk_ids":[]}
```

Each case may include `sources`, a list of immutable document IDs to restrict retrieval in the non-streaming chat API. Omit it to search all indexed documents. This is useful for comparing like-for-like runs when an isolated corpus contains additional documents.

Cases may also include a `filters` object with `pages`, `content_types`, `created_from`, `created_to`, or `tags`. The capture command forwards it to the same retrieval path used by chat. Dates are inclusive ISO dates. Requested page and content-type filters exclude older chunks lacking that metadata; re-ingest those PDFs before testing filtered retrieval. Tags are attached to registered documents through `PATCH /api/documents/{id}/tags` or the chat sidebar.

For follow-up cases, add `history` as up to six prior `{ "role": "user" | "assistant", "content": "..." }` turns. The capture command passes this to non-streaming chat; streamed chat loads its own bounded history from the saved conversation. The retrieval query may be rewritten, while the answer still uses the original question.

Include text, table, image, multi-turn, cross-document, and deliberately unsupported questions. Review the evidence manually before marking chunks relevant. Keep the corpus, indexed document IDs, case file, model configuration, and `k` fixed across runs. A new ingestion creates new document IDs, so remap the gold IDs before comparison. Do not commit private PDFs or answer content.

From `mmr-backend`, capture a baseline with the running API (this invokes the answer model and may incur API charges):

```bash
venv/bin/python -m scripts.capture_predictions --cases evaluation/cases.jsonl --output evaluation/baseline_predictions.jsonl --k 3
venv/bin/python -m scripts.evaluate --cases evaluation/cases.jsonl --predictions evaluation/baseline_predictions.jsonl --k 3 --output evaluation/baseline_report.json
```

The capture command only writes a complete run. The scorer requires one prediction per case. Add `groundedness` and `answer_quality` ratings in `[0, 1]` to each prediction after human review. Missing ratings remain `null` in the aggregate, with coverage counts; they are never inferred from retrieval scores. Groundedness asks whether every factual claim is supported by its cited evidence. Answer quality asks whether the answer addresses the question correctly and completely. Record the rating rubric and reviewers alongside the case set.

`retrieval_recall_at_k` is the mean fraction of each answerable question's gold chunks found in the first `k` results. `mean_reciprocal_rank_at_k` measures how early the first gold chunk appears. `citation_precision` is the share of unique cited chunk IDs that are both retrieved and labeled relevant; it does **not** prove claim-level support. `abstention_accuracy` measures whether the response abstains on unanswerable questions and answers answerable ones. Human groundedness and answer-quality ratings are reported separately. A null metric means there is no suitable denominator, not a zero score.

For a smoke test of the scorer, run it with `evaluation/example_cases.jsonl` and `evaluation/example_predictions.jsonl`. Do not compare that report against live results.

## Fixed retrieval fixture

`fixture_corpus.jsonl` contains seven synthetic chunks spanning policy prose, table-like financial data, OCR processing, and an image-description chunk. `fixture_cases.jsonl` contains six labeled questions, including a two-chunk comparison and one unsupported question. This fixture is useful for detecting retrieval regressions; it bypasses PDF extraction and answer generation, so it is **not** a representative PDF or answer-quality benchmark.

With a configured OpenAI API key, run the three retrieval configurations in an isolated temporary Chroma collection:

```bash
venv/bin/python -m scripts.fixture_benchmark --output-dir /tmp/mmr-phase3-k3 --k 3
venv/bin/python -m scripts.fixture_benchmark --output-dir /tmp/mmr-phase3-k1 --k 1
```

The script writes predictions and full reports to the chosen output directory, never the application's document registry or persistent index. It makes paid embedding API calls. On October 21, 2026, semantic-only, hybrid, and hybrid-plus-reranking all measured recall@3 = 1.00 and abstention accuracy = 1.00 on this small fixture. At `k=1`, all three measured mean recall = 0.80 and abstention accuracy = 1.00; two cases require two gold chunks, so top-1 cannot reach perfect recall. Citation precision, groundedness, and answer quality were unscored because this is a retrieval-only run. The fixture showed **no measured improvement** over the Phase 2 semantic baseline. A representative, manually reviewed PDF corpus is still needed before tuning thresholds or claiming quality gains. This evaluation was deferred at the user's request on October 21, 2026; existing local PDFs are not to be used for it.
