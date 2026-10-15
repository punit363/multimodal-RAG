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

The workspace contains two independent Git repositories:

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
npm run dev
```

Open `http://localhost:3000`.

## Run with Docker Compose

Create `mmr-backend/.env` from the example file, add your API key, then run:

```bash
docker compose up --build
```

The Compose setup persists uploaded files, the SQLite database, and the Chroma index in named volumes.

## Validation

```bash
cd mmr-backend
python -m unittest discover -s tests -v

cd ../mmr-frontend
npm run lint
npm run build
```

The current stabilization plan and remaining tasks are tracked in [CODEX.md](CODEX.md).

## Current limitations

- Only PDF uploads are supported.
- The frontend currently targets a backend on `http://localhost:8000`.
- Authentication and workspace isolation are not implemented.
- Ingestion runs within the API process and is intended for local MVP use.
- Page-level citations and retrieval-quality evaluation are planned for a later phase.

