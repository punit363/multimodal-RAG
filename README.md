# MultiModal RAG

MultiModal RAG is a document-question-answering application for PDFs containing text, tables, and images. The backend partitions and chunks uploaded PDFs, creates searchable multimodal summaries, stores embeddings in Chroma, and streams grounded answers. The frontend provides document selection, ingestion progress, conversation history, and citation previews.

## Architecture

```text
Browser (Next.js)
  |-- upload PDF / stream progress ------> FastAPI
  |-- ask question / stream answer ------> FastAPI
  |<-- answer + retrieved source chunks --|
                                               |-- Unstructured: PDF parsing
                                               |-- OpenAI: summaries, embeddings, answers
                                               |-- Chroma: vector index
                                               `-- SQLite: documents and conversations
```

The root repository contains two application services:

- `mmr-frontend`: Next.js, React, TypeScript, and Tailwind CSS.
- `mmr-backend`: FastAPI, LangChain, Unstructured, Chroma, and SQLite.

## Prerequisites

- Node.js 20 or newer
- Python 3.11
- An OpenAI API key
- PDF extraction system packages required by Unstructured
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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API health endpoint is available at `http://localhost:8000/` and interactive API documentation at `http://localhost:8000/docs`.

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

The completed Phase 1 record and the prioritized Phase 2 roadmap are tracked in [CODEX.md](CODEX.md). The [Phase 2 engineering log](https://app.notion.com/p/3fa7cd5908fc81d0956ce0e18f7cad66) records implementation evidence after each priority is complete.

## Current limitations

- Only PDF uploads are supported.
- Authentication and workspace isolation are not implemented.
- Ingestion runs within the API process and is intended for local MVP use.
- Phase 2 High priority adds cited PDF source navigation and an insufficient-evidence response. The remaining answer controls, feedback, and relevance display are planned; retrieval-quality evaluation remains planned for a later phase.

## Answer grounding

`RAG_MIN_RELEVANCE_SCORE` defaults to `0.35`. The score is the vector store's normalized cosine relevance measure, with larger values indicating a closer match. It is a retrieval heuristic, not a calibrated probability. When every retrieved chunk scores below the threshold, both chat endpoints return an explicit insufficient-evidence answer without calling the answer model. The threshold should be tuned against a representative evaluation set before treating it as a quality guarantee.

## Runtime safety behavior

- Uploads are checked for PDF extension, MIME type, signature, size, readability, encryption, and page count before ingestion.
- Stored files use generated document IDs, so duplicate display filenames cannot overwrite each other.
- Extracted table HTML is sanitized before indexing and again before retrieval.
- Failed or cancelled ingestion removes partial vectors, files, and registry data; cleanup failures are quarantined and recorded.
- Deletion uses a retryable lifecycle state so cross-store failures remain visible and recoverable.
- The UI applies request timeouts and exposes retry and cancellation controls for uploads and streamed answers.

