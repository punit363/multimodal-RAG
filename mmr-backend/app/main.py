# app/main.py

import os
import json
import uuid
import asyncio
import logging
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader

from app.rag_pipeline import (
    partition_documents,
    create_chunks_by_title,
    build_documents,
    store_documents,
    answer_query,
    answer_query_stream,
    delete_document_vectors,
)
from app.retrieval_filters import RetrievalFilters
from app.database import (
    init_db,
    create_conversation,
    get_all_conversations,
    get_recent_messages,
    save_message,
    update_message_content,
    set_message_feedback,
    add_document,
    list_documents,
    get_document,
    delete_document_record,
    update_document_status,
    set_document_tags,
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
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "RAG_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.getenv("RAG_UPLOAD_DIR", "docs")
MAX_UPLOAD_BYTES = int(os.getenv("RAG_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_PDF_PAGES = int(os.getenv("RAG_MAX_PDF_PAGES", "200"))
QUARANTINE_DIR = os.path.join(UPLOAD_DIR, ".quarantine")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(QUARANTINE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=500)


class QueryRequest(BaseModel):
    query: str
    top_k: int = Field(default=3, ge=1, le=20)
    sources: Optional[List[str]] = None
    filters: Optional[RetrievalFilters] = None
    history: List[HistoryMessage] = Field(default_factory=list, max_length=6)


class StreamQueryRequest(BaseModel):
    query: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    top_k: int = Field(default=3, ge=1, le=20)
    # Immutable document ids selected as sources. None/empty = search everything.
    sources: Optional[List[str]] = None
    filters: Optional[RetrievalFilters] = None


class CreateConvRequest(BaseModel):
    title: str = "New Conversation"


class FeedbackRequest(BaseModel):
    feedback: Optional[Literal["helpful", "not_helpful"]]


class TagsRequest(BaseModel):
    tags: List[str] = Field(max_length=20)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: List[str]) -> List[str]:
        normalized = [tag.strip() for tag in tags]
        if any(not tag or len(tag) > 40 for tag in normalized):
            raise ValueError("Tags must be non-empty and at most 40 characters.")
        return list(dict.fromkeys(normalized))


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


async def _save_and_validate_pdf(file: UploadFile, file_path: str) -> None:
    filename = os.path.basename(file.filename or "")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="The uploaded file must use the application/pdf MIME type.")

    total = 0
    signature = b""
    try:
        with open(file_path, "wb") as destination:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"PDF exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
                    )
                if not signature:
                    signature = chunk[:5]
                destination.write(chunk)
    except Exception:
        Path(file_path).unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if signature != b"%PDF-":
        Path(file_path).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file does not have a valid PDF signature.")

    try:
        reader = await asyncio.to_thread(PdfReader, file_path)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported.")
        page_count = len(reader.pages)
    except ValueError as exc:
        Path(file_path).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        Path(file_path).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded PDF is malformed or unreadable.") from exc

    if page_count == 0 or page_count > MAX_PDF_PAGES:
        Path(file_path).unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"PDF must contain between 1 and {MAX_PDF_PAGES} pages.",
        )


async def _cleanup_failed_ingestion(doc_id: str, file_path: str, reason: str) -> None:
    cleanup_errors = []
    try:
        await asyncio.to_thread(delete_document_vectors, doc_id)
    except Exception as exc:
        cleanup_errors.append(f"vector cleanup: {exc}")

    if not cleanup_errors:
        try:
            Path(file_path).unlink(missing_ok=True)
            delete_document_record(doc_id)
            return
        except Exception as exc:
            cleanup_errors.append(f"storage cleanup: {exc}")

    try:
        if os.path.exists(file_path):
            os.replace(file_path, os.path.join(QUARANTINE_DIR, f"{doc_id}.pdf.failed"))
        update_document_status(
            doc_id,
            "failed",
            f"{reason}; cleanup pending: {'; '.join(cleanup_errors)}",
        )
    except Exception:
        logger.exception("Failed to quarantine partial ingestion %s", doc_id)


async def _run_ingestion_step(function, *args):
    """Finish an active worker before propagating cancellation to avoid cleanup races."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


@app.post("/api/ingest-stream")
async def ingest_document_stream(file: UploadFile = File(...)):
    """Upload a PDF and stream step-by-step progress events."""
    filename = os.path.basename(file.filename or "")
    document_id = str(uuid.uuid4())
    storage_name = f"{document_id}.pdf"
    file_path = os.path.join(UPLOAD_DIR, storage_name)
    await _save_and_validate_pdf(file, file_path)
    add_document(
        filename,
        doc_id=document_id,
        storage_name=storage_name,
        status="processing",
    )

    async def event_generator():
        try:
            yield _sse({"step": 1, "label": "Partitioning PDF Layout...", "status": "in_progress"})
            elements = await _run_ingestion_step(partition_documents, file_path)

            yield _sse({"step": 2, "label": "Extracting Text, Tables & Images...", "status": "in_progress"})
            chunks = await _run_ingestion_step(create_chunks_by_title, elements)

            yield _sse({"step": 3, "label": "Generating Multi-Modal AI Summaries...", "status": "in_progress"})
            documents = await _run_ingestion_step(
                build_documents, chunks, filename, document_id
            )

            yield _sse({"step": 4, "label": "Generating Embeddings & Storing in ChromaDB...", "status": "in_progress"})
            await _run_ingestion_step(store_documents, documents)

            update_document_status(document_id, "ready")
            yield _sse({
                "step": 5,
                "label": "Document Indexing Complete!",
                "status": "completed",
                "filename": filename,
                "document_id": document_id,
            })
        except asyncio.CancelledError:
            await asyncio.shield(
                _cleanup_failed_ingestion(document_id, file_path, "Upload cancelled")
            )
            raise
        except Exception as e:
            logger.exception("Ingestion failed")
            await _cleanup_failed_ingestion(document_id, file_path, str(e))
            yield _sse({
                "step": -1,
                "label": "Ingestion failed. The partial document was cleaned up; retry the upload.",
                "status": "error",
                "retryable": True,
            })

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
        options = {"filters": request.filters} if request.filters and request.filters.active() else {}
        if request.history:
            options["history"] = [message.model_dump() for message in request.history]
        return answer_query(request.query, k=request.top_k, sources=request.sources or None, **options)
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
    history = get_recent_messages(request.conversation_id)

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
        stream_error = ""

        try:
            options = {"filters": request.filters} if request.filters and request.filters.active() else {}
            if history:
                options["history"] = history
            for sse_line in answer_query_stream(
                request.query, k=request.top_k, sources=request.sources or None, **options
            ):
                yield sse_line

                if sse_line.startswith("data: "):
                    try:
                        data = json.loads(sse_line[len("data: "):].strip())
                        if data.get("type") == "sources":
                            retrieved_sources = data.get("sources", [])
                        elif data.get("type") == "token":
                            accumulated_answer += data.get("token", "")
                        elif data.get("type") == "error":
                            stream_error = data.get("message", "Answer generation failed.")
                    except Exception:
                        pass
        finally:
            # 4. Persist the full answer once the stream ends (or is aborted)
            update_message_content(
                msg_id=request.assistant_message_id,
                content=(
                    accumulated_answer
                    or (f"Answer failed: {stream_error}" if stream_error else "Answer stream was interrupted. Retry the question.")
                ),
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


@app.patch("/api/messages/{message_id}/feedback")
def update_feedback(message_id: str, request: FeedbackRequest):
    """Persist or clear feedback for one assistant answer."""
    if not set_message_feedback(message_id, request.feedback):
        raise HTTPException(status_code=404, detail="Assistant message not found.")
    return {"message_id": message_id, "feedback": request.feedback}


# ---------------------------------------------------------------------------
# Documents (list / delete)
# ---------------------------------------------------------------------------

@app.get("/api/documents")
def get_documents():
    """List every indexed document."""
    documents = list_documents()
    for document in documents:
        storage_name = document.get("storage_name") or document["filename"]
        document["source_id"] = (
            document["filename"] if storage_name == document["filename"] else document["id"]
        )
    return documents


@app.patch("/api/documents/{doc_id}/tags")
def update_document_tags(doc_id: str, request: TagsRequest):
    """Assign searchable labels to a ready document."""
    if not set_document_tags(doc_id, request.tags):
        raise HTTPException(status_code=404, detail="Ready document not found.")
    return get_document(doc_id)


@app.get("/api/documents/{doc_id}/pdf")
def get_document_pdf(doc_id: str):
    """Serve only a registered, ready PDF from the upload directory."""
    document = get_document(doc_id)
    if not document or document.get("status") not in (None, "ready"):
        raise HTTPException(status_code=404, detail="Document not found.")
    storage_name = document.get("storage_name") or document["filename"]
    if Path(storage_name).name != storage_name or not storage_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="Document not found.")
    file_path = Path(UPLOAD_DIR) / storage_name
    if file_path.resolve().parent != Path(UPLOAD_DIR).resolve() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found.")
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=document["filename"],
        content_disposition_type="inline",
    )


@app.delete("/api/documents/{doc_id}")
def remove_document(doc_id: str):
    """Delete a document's vectors, its registry row and the uploaded PDF."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    storage_name = doc.get("storage_name") or doc["filename"]
    file_path = os.path.join(UPLOAD_DIR, storage_name)
    quarantine_path = os.path.join(QUARANTINE_DIR, f"{doc_id}.pdf.deleting")
    vectors_deleted = False
    try:
        update_document_status(doc_id, "deleting")
        if os.path.exists(file_path):
            os.replace(file_path, quarantine_path)
        vector_key = doc["filename"] if storage_name == doc["filename"] else doc_id
        delete_document_vectors(vector_key)
        vectors_deleted = True
        delete_document_record(doc_id)
        Path(quarantine_path).unlink(missing_ok=True)
    except Exception as e:
        logger.exception("Document deletion failed")
        if not vectors_deleted and os.path.exists(quarantine_path):
            os.replace(quarantine_path, file_path)
        try:
            update_document_status(doc_id, "deletion_failed", str(e))
        except Exception:
            logger.exception("Could not mark deletion failure for %s", doc_id)
        raise HTTPException(
            status_code=500,
            detail="Document deletion did not finish. Its state was preserved for retry.",
        ) from e

    return {"status": "deleted", "id": doc_id}
