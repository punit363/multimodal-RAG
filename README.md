# MultiModal RAG

MultiModal RAG is a document-question-answering application for PDFs, Office files, images, and web pages. The backend extracts and chunks sources, stores searchable evidence in Chroma, and streams grounded answers. The frontend provides document organization, ingestion progress, conversation history, summaries, and citation previews.

## Architecture

```text
Browser (Next.js)
  |-- upload sources / stream progress --> FastAPI
  |-- ask question / stream answer ------> FastAPI
  |<-- answer + retrieved source chunks --|
                                               |-- Unstructured: PDF parsing
                                               |-- OpenAI: summaries, embeddings, answers
                                               |-- Chroma: vector index
                                               `-- SQLite: documents, conversations, shares
```

The root repository contains two application services:

- `mmr-frontend`: Next.js, React, TypeScript, and Tailwind CSS.
- `mmr-backend`: FastAPI, LangChain, Unstructured, Chroma, and SQLite.

## Prerequisites

- Node.js 20 or newer
- Python 3.11
- An OpenAI API key
- Tesseract with English, Hindi, Spanish, and French language packs for multilingual OCR (included in the Docker backend image)
- Docker Desktop, if using the container setup

## Run locally

### Backend

```bash
cd mmr-backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set OPENAI_API_KEY in .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-access-log
```

The API health endpoint is available at `http://localhost:8000/` and interactive API documentation at `http://localhost:8000/docs`. Set `RAG_OCR_LANGUAGES` to a comma-separated subset of `en,hi,es,fr` if only some OCR packs are installed locally.

### Frontend

```bash
cd mmr-frontend
npm ci
cp .env.example .env.local
npm run dev
```

Open `http://localhost:3000`.

`NEXT_PUBLIC_API_BASE_URL` is validated during the frontend build and defaults to `http://localhost:8000`. Set it in `mmr-frontend/.env.local` for a different backend origin.

For a guided product walkthrough with screenshots, see [docs/DEMO.md](docs/DEMO.md).

## Run with Docker Compose

Create `mmr-backend/.env` from the example file, add your API key, then run:

```bash
docker compose up --build
```

If port 3000 is already in use, choose an alternate frontend host port without changing the container configuration:

```bash
FRONTEND_PORT=3001 docker compose up --build
```

Set `NEXT_PUBLIC_API_BASE_URL` before the build when the browser must reach the backend at another public origin:

```bash
NEXT_PUBLIC_API_BASE_URL=https://rag-api.example.com docker compose up --build
```

The Compose setup persists uploaded files, the SQLite database, and the Chroma index in named volumes.

The backend image includes OCR and document-inference dependencies. Keep several gigabytes of free Docker storage available for the first build.

## Validation

```bash
cd mmr-backend
python -m unittest discover -s tests -v

cd ../mmr-frontend
npm run lint
npm test
npm run build
npm run test:e2e
```

The completed Phase 1 and Phase 2 records and the prioritized Phase 3 roadmap are tracked in [CODEX.md](CODEX.md). The [Phase 3 engineering log](https://app.notion.com/p/3fa7cd5908fc81eda42bfc938e72f64c) records implementation evidence after each priority. The [evaluation guide](mmr-backend/evaluation/README.md) explains how to capture a fixed Phase 2 baseline before tuning retrieval.

## Current limitations

- DOCX, PPTX, XLSX, image, and HTML extraction currently indexes text. PDF extraction also preserves tables and images. Image files require Tesseract OCR; non-PDF source cards download the original file rather than opening the PDF viewer.
- The owner key provides one protected workspace, not separate user accounts or per-user document ownership. Configure it before creating share links; full multi-user identity and governance remain Phase 5 work.
- Ingestion runs within the API process and is intended for local MVP use.
- Phase 2 is complete. Existing PDFs need re-ingestion for new element-type, location-status, and content-type metadata. A representative quality evaluation remains open in Phase 3.
- Source cards show normalized cosine retrieval similarity from 0 to 100%; scores below 50% are marked **Weak match**. This measures question-to-chunk similarity, not answer correctness or model confidence.

## Answer grounding

`RAG_MIN_RELEVANCE_SCORE` defaults to `0.35`. The score is the vector store's normalized cosine relevance measure, with larger values indicating a closer match. It is a retrieval heuristic, not a calibrated probability. Semantic candidates below this threshold are excluded. Hybrid mode may also accept exact-term keyword candidates with at least 75% meaningful query-term coverage and cosine similarity of at least `RAG_MIN_RELEVANCE_SCORE - 0.10`. Both chat paths return an explicit insufficient-evidence answer when neither gate admits a candidate. Tune these heuristics against a representative evaluation set before treating them as quality guarantees.

Phase 3 adds `RAG_RETRIEVAL_MODE=hybrid` (the default) to combine normalized cosine and exact-term BM25 candidates with reciprocal-rank fusion. Set `RAG_RETRIEVAL_MODE=semantic` to reproduce the Phase 2 retrieval path. `RAG_RERANK_ENABLED=true` applies a bounded diversity reranker after fusion. The displayed source score remains cosine similarity, not the fused ranking score. Hybrid retrieval scans the local Chroma corpus for keyword candidates, so it is intended for the current local-scale MVP. Quality gains have not yet been measured against a representative fixed corpus.

`RAG_QUERY_REWRITE_ENABLED=true` rewrites follow-up questions for retrieval using up to six previous messages from the same conversation. Only the retrieval query changes; the answer is generated for the original question. Disable it when measuring the Phase 2 baseline. Non-streaming evaluation cases can supply bounded `history` explicitly; streamed chat loads history from SQLite before saving the current question.

The chat filter bar narrows evidence by selected documents, PDF page, content type, upload date, and document tags. Tags can be edited beside each ready document. Date bounds are inclusive. Missing page or content-type metadata does not match a requested filter, so re-ingest older PDFs before applying those filters. The benchmark instructions and fixture-only results are in the [evaluation guide](mmr-backend/evaluation/README.md).

Newly ingested PDFs are chunked within page and section boundaries. Text, table-cell text, and image descriptions get separate searchable vectors with a shared section parent ID and distinct citation IDs. Source cards identify the document, section, evidence type, and available PDF page. Re-ingest existing PDFs to gain this index layout; existing vectors remain readable until then. Image descriptions use the configured model during ingestion, so image-heavy PDFs can require more processing and API usage.

Enable **Compare selected documents** in chat after selecting two to four ready PDFs. The backend retrieves evidence from each selected document and requires registered citations from every document in the generated comparison. If one document has no matching evidence, it returns the insufficient-evidence response; if the generated comparison omits a document citation, it shows a verification failure instead. The non-streaming API also accepts `"mode": "compare"` with two to four distinct `sources` IDs. Representative comparison quality has not been measured because that evaluation was deferred.

Phase 4 accepts PDF, DOCX, PPTX, XLSX, PNG/JPEG/WebP/TIFF, and HTML files in the upload queue. Paste a public HTTP(S) URL into **Add page** to ingest its HTML; private network destinations, redirects, and oversized pages are rejected. Files run in sequence, each file has a visible outcome, and failures can be retried independently. In the Knowledge Base sidebar, **Save selection** persists named source sets. Create folders, move documents, and filter by folder. **Summary** shows short extractive excerpts with source chunk IDs for a document, section, or saved set. **Review** shows extraction warnings and previews, and records an accepted or needs-attention decision. Low-text PDF pages and image OCR are flagged for review. These checks are heuristics; verify important facts against the original source.

Select ready sources and use **Cited output** to create fact extraction, a timeline, a section comparison matrix, or a Markdown report. Evidence-bearing items carry an indexed chunk ID; missing matrix evidence is labelled unavailable. **Download cited report** saves a Markdown copy. These are extractive views of indexed text, not generated conclusions. Choose an answer language from Auto, English, Hindi, Spanish, or French. Auto detects Hindi script and otherwise uses English; unsupported scripts return a validation error. The Dockerfile installs OCR packs for all four languages; this image has not been rebuilt in the current environment. Language quality on representative documents has not yet been measured.

To enable sharing, set a random `RAG_OWNER_API_KEY` of at least 32 characters in `mmr-backend/.env`, restart the backend, and enter that key in the workspace's **Unlock** dialog. Private API routes then require a 24-hour owner session. Use **Share set** or **Share chat** to create a seven-day view-only or comment-enabled link; copy it when created because the token is stored only as a hash. The owner can revoke links in the workspace. A shared page can show its scoped content and comments without exposing other private API routes. Use the same hostname for the frontend and backend (for example, `localhost` on both ports) so the owner cookie is sent, and use HTTPS before exposing the app outside a trusted local network. If the owner key is unset, the existing local workspace remains open and share creation is disabled. This is a single-owner MVP, not multi-user account management.

## Runtime safety behavior

- PDFs are checked for extension, MIME type, signature, size, readability, encryption, and page count. Other formats use MIME, size, signature/container, and extractor checks.
- Stored files use generated document IDs, so duplicate display filenames cannot overwrite each other.
- Extracted table HTML is sanitized before indexing and again before retrieval.
- Failed or cancelled ingestion removes partial vectors, files, and registry data; cleanup failures are quarantined and recorded.
- Deletion uses a retryable lifecycle state so cross-store failures remain visible and recoverable.
- The UI applies request timeouts and exposes retry and cancellation controls for uploads and streamed answers.

