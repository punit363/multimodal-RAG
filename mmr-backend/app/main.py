# app/main.py

import os
import json
import uuid
import shutil
import asyncio
import logging
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.rag_pipeline import (
    partition_documents,
    create_chunks_by_title,
    build_documents,
    store_documents,
    answer_query,
    answer_query_stream,
    delete_document_vectors,
)
from app.database import (
    init_db,
    create_conversation,
    get_all_conversations,
    save_message,
    update_message_content,
    add_document,
    list_documents,
    get_document,
    delete_document_record,
)

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="Multi-Modal RAG API")


# ---------------------------------------------------------------------------
# Startup & middleware
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup_event():
    init_db()


# Single CORS config. Wildcard origins are invalid together with
# allow_credentials=True, so list the frontend origins explicitly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "docs"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str
    top_k: int = 3


class StreamQueryRequest(BaseModel):
    query: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    top_k: int = 3
    # Filenames the user selected as sources. None/empty = search everything.
    sources: Optional[List[str]] = None


class CreateConvRequest(BaseModel):
    title: str = "New Conversation"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Multi-Modal RAG API is running"}


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.post("/api/ingest-stream")
async def ingest_document_stream(file: UploadFile = File(...)):
    """Upload a PDF and stream step-by-step progress events."""
    filename = os.path.basename(file.filename or "")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_path = os.path.join(UPLOAD_DIR, filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    async def event_generator():
        try:
            # Step 1: partition the PDF layout (slow, done once)
            yield _sse({"step": 1, "label": "Partitioning PDF Layout...", "status": "in_progress"})
            elements = await asyncio.to_thread(partition_documents, file_path)

            # Step 2: chunk + categorise content (text / tables / images)
            yield _sse({"step": 2, "label": "Extracting Text, Tables & Images...", "status": "in_progress"})
            chunks = await asyncio.to_thread(create_chunks_by_title, elements)

            # Step 3: multi-modal AI summaries
            yield _sse({"step": 3, "label": "Generating Multi-Modal AI Summaries...", "status": "in_progress"})
            documents = await asyncio.to_thread(build_documents, chunks, filename)

            # Step 4: embeddings + vector store (replaces any previous upload of this file)
            yield _sse({"step": 4, "label": "Generating Embeddings & Storing in ChromaDB...", "status": "in_progress"})
            await asyncio.to_thread(delete_document_vectors, filename)
            await asyncio.to_thread(store_documents, documents)

            doc = add_document(filename)
            yield _sse({
                "step": 5,
                "label": "Document Indexing Complete!",
                "status": "completed",
                "filename": filename,
                "document_id": doc["id"],
            })
        except Exception as e:
            logger.exception("Ingestion failed")
            yield _sse({"step": -1, "label": f"Error: {e}", "status": "error"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.post("/api/chat")
def chat_query(request: QueryRequest):
    """Non-streaming query."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query string cannot be empty.")
    try:
        return answer_query(request.query, k=request.top_k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {e}")


@app.post("/api/chat-stream")
def chat_query_stream(request: StreamQueryRequest):
    """Stream LLM tokens over SSE and persist both messages to SQLite.

    Declared as a plain `def` so Starlette iterates the (sync) generator in a
    threadpool instead of blocking the event loop.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query string cannot be empty.")

    # 1. Make sure the conversation exists
    create_conversation(request.conversation_id, request.query[:25])

    # 2. Save the user message right away
    save_message(
        msg_id=request.user_message_id,
        conv_id=request.conversation_id,
        role="user",
        content=request.query,
    )

    # 3. Save an empty assistant placeholder (filled in when streaming ends)
    save_message(
        msg_id=request.assistant_message_id,
        conv_id=request.conversation_id,
        role="assistant",
        content="",
    )

    def event_generator():
        accumulated_answer = ""
        retrieved_sources = []

        try:
            for sse_line in answer_query_stream(
                request.query, k=request.top_k, sources=request.sources or None
            ):
                yield sse_line

                if sse_line.startswith("data: "):
                    try:
                        data = json.loads(sse_line[len("data: "):].strip())
                        if data.get("type") == "sources":
                            retrieved_sources = data.get("sources", [])
                        elif data.get("type") == "token":
                            accumulated_answer += data.get("token", "")
                    except Exception:
                        pass
        finally:
            # 4. Persist the full answer once the stream ends (or is aborted)
            update_message_content(
                msg_id=request.assistant_message_id,
                content=accumulated_answer or "Completed.",
                sources=retrieved_sources,
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@app.get("/api/conversations")
def list_conversations():
    """Fetch all persisted conversations and their messages."""
    return get_all_conversations()


@app.post("/api/conversations")
def new_conversation(req: CreateConvRequest):
    """Create a new conversation record."""
    conv_id = str(uuid.uuid4())
    return create_conversation(conv_id, req.title)


# ---------------------------------------------------------------------------
# Documents (list / delete)
# ---------------------------------------------------------------------------

@app.get("/api/documents")
def get_documents():
    """List every indexed document."""
    return list_documents()


@app.delete("/api/documents/{doc_id}")
def remove_document(doc_id: str):
    """Delete a document's vectors, its registry row and the uploaded PDF."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    try:
        delete_document_vectors(doc["filename"])
    except Exception as e:
        logger.exception("Failed to delete vectors")
        raise HTTPException(status_code=500, detail=f"Could not delete vectors: {e}")

    delete_document_record(doc_id)

    file_path = os.path.join(UPLOAD_DIR, doc["filename"])
    if os.path.exists(file_path):
        os.remove(file_path)

    return {"status": "deleted", "id": doc_id}