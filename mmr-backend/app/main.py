# app/main.py

import os
import json
import uuid
import asyncio
import logging
import ipaddress
import socket
import ssl
import http.client
import io
import hmac
import hashlib
import time
from urllib.parse import urlsplit
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, Response, JSONResponse
from starlette.datastructures import Headers
from pydantic import BaseModel, Field, field_validator, model_validator
from pypdf import PdfReader

from app.rag_pipeline import (
    partition_documents,
    create_chunks_by_title,
    build_documents,
    store_documents,
    answer_query,
    answer_query_stream,
    delete_document_vectors,
    summarize_evidence,
    indexed_evidence,
)
from app.structured_outputs import build_structured_output
from app.language import response_language
from app.operations import readiness_checks
from app.request_log import log_request
from app.controls import enforce_controls
from app.retrieval_filters import RetrievalFilters
from app.document_extract import extract_sections
from app.database import (
    init_db,
    create_conversation,
    delete_conversation,
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
    list_source_sets,
    create_source_set,
    update_source_set,
    delete_source_set,
    list_folders,
    create_folder,
    rename_folder,
    delete_folder,
    set_document_folder,
    set_document_extraction,
    set_extraction_review,
    set_source_format,
    create_share,
    list_shares,
    get_share_by_token,
    revoke_share,
    add_share_comment,
    list_share_comments,
    list_audit_events,
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

# Inside owner_access: unauthenticated private calls do not consume owner quotas.
app.middleware("http")(enforce_controls)


def _owner_key() -> str:
    return os.getenv("RAG_OWNER_API_KEY", "")


def _owner_session_valid(cookie: Optional[str]) -> bool:
    key = _owner_key()
    if not key or not cookie:
        return False
    try:
        issued, signature = cookie.split(".", 1)
        issued_at = int(issued)
        if not 0 <= time.time() - issued_at < 24 * 60 * 60:
            return False
        expected = hmac.new(key.encode(), issued.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False


@app.middleware("http")
async def owner_access(request: Request, call_next):
    """Keep private APIs behind an owner session when sharing is enabled."""
    path = request.url.path
    public = path in {"/", "/health/live", "/health/ready", "/api/auth/status", "/api/auth/login"} or path.startswith("/api/public-shares/")
    if request.method == "OPTIONS" or not _owner_key() or public or _owner_session_valid(request.cookies.get("rag_owner")):
        return await call_next(request)
    response = JSONResponse(status_code=401, content={"detail": "Owner session required."})
    origin = request.headers.get("origin")
    if origin in cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


# Registered after owner_access so rejected requests also get a correlation ID.
app.middleware("http")(log_request)

UPLOAD_DIR = os.getenv("RAG_UPLOAD_DIR", "docs")
VECTOR_DIR = os.getenv("RAG_VECTOR_DIR", "db/chroma_db")
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


class ComparisonRequest(BaseModel):
    mode: Literal["answer", "compare"] = "answer"
    sources: Optional[List[str]] = None

    @model_validator(mode="after")
    def validate_comparison(self):
        if self.mode == "compare" and (
            not self.sources or not 2 <= len(self.sources) <= 4
            or len(set(self.sources)) != len(self.sources)
            or any(not source.strip() for source in self.sources)
        ):
            raise ValueError("Comparison requires two to four distinct selected documents.")
        return self


class QueryRequest(ComparisonRequest):
    query: str
    top_k: int = Field(default=3, ge=1, le=20)
    filters: Optional[RetrievalFilters] = None
    history: List[HistoryMessage] = Field(default_factory=list, max_length=6)
    language: Literal["auto", "en", "hi", "es", "fr"] = "auto"


class StreamQueryRequest(ComparisonRequest):
    query: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    top_k: int = Field(default=3, ge=1, le=20)
    # Immutable document ids selected as sources. None/empty = search everything.
    filters: Optional[RetrievalFilters] = None
    language: Literal["auto", "en", "hi", "es", "fr"] = "auto"


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


class SourceSetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    document_ids: List[str] = Field(min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("A source-set name is required.")
        return name

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, document_ids: List[str]) -> List[str]:
        if len(set(document_ids)) != len(document_ids) or any(not item.strip() for item in document_ids):
            raise ValueError("Document IDs must be distinct and non-empty.")
        return document_ids


class FolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        return name.strip()


class MoveDocumentRequest(BaseModel):
    folder_id: Optional[str] = None


class ExtractionReviewRequest(BaseModel):
    status: Literal["accepted", "needs_attention"]
    note: str = Field(default="", max_length=500)


class WebPageRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2048)


class OutputRequest(BaseModel):
    kind: Literal["extraction", "timeline", "matrix", "report"]
    document_ids: List[str] = Field(min_length=1, max_length=10)

    @field_validator("document_ids")
    @classmethod
    def distinct_ids(cls, ids: List[str]) -> List[str]:
        if len(ids) != len(set(ids)) or any(not item.strip() for item in ids):
            raise ValueError("Select distinct document IDs.")
        return ids


class OwnerLoginRequest(BaseModel):
    key: str = Field(min_length=1, max_length=512)


class ShareRequest(BaseModel):
    resource_type: Literal["collection", "conversation"]
    resource_id: str = Field(min_length=1, max_length=100)
    permission: Literal["view", "comment"] = "view"
    expires_in_days: int = Field(default=7, ge=1, le=30)


class ShareCommentRequest(BaseModel):
    author: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=1000)

    @field_validator("author", "body")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Text cannot be empty.")
        return value


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Multi-Modal RAG API is running"}


@app.get("/health/live")
def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
def health_ready():
    checks = readiness_checks(UPLOAD_DIR, VECTOR_DIR)
    ready = all(status == "ok" for status in checks.values())
    return JSONResponse(status_code=200 if ready else 503, content={
        "status": "ready" if ready else "not_ready", "checks": checks,
    })


@app.get("/api/auth/status")
def auth_status(request: Request):
    required = bool(_owner_key())
    return {"required": required, "authenticated": not required or _owner_session_valid(request.cookies.get("rag_owner"))}


@app.post("/api/auth/login")
def owner_login(request: Request, credentials: OwnerLoginRequest):
    key = _owner_key()
    if not key or not hmac.compare_digest(credentials.key, key):
        raise HTTPException(status_code=401, detail="Invalid owner key.")
    issued = str(int(time.time()))
    signature = hmac.new(key.encode(), issued.encode(), hashlib.sha256).hexdigest()
    response = JSONResponse({"authenticated": True})
    response.set_cookie("rag_owner", f"{issued}.{signature}", httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", max_age=24 * 60 * 60, path="/api")
    return response


@app.post("/api/auth/logout")
def owner_logout():
    response = JSONResponse({"authenticated": False})
    response.delete_cookie("rag_owner", path="/api")
    return response


@app.get("/api/shares")
def get_shares():
    return list_shares()


@app.get("/api/audit-events")
def get_audit_events(limit: int = 50):
    return list_audit_events(limit)


@app.post("/api/shares")
def save_share(request: ShareRequest):
    if len(_owner_key()) < 32:
        raise HTTPException(status_code=503, detail="Set a strong RAG_OWNER_API_KEY (at least 32 characters) before sharing.")
    if request.resource_type == "collection":
        exists = any(item["id"] == request.resource_id for item in list_source_sets())
    else:
        exists = any(item["id"] == request.resource_id for item in get_all_conversations())
    if not exists:
        raise HTTPException(status_code=404, detail="Share target not found.")
    return create_share(request.resource_type, request.resource_id, request.permission, request.expires_in_days)


@app.delete("/api/shares/{share_id}")
def remove_share(share_id: str):
    if not revoke_share(share_id):
        raise HTTPException(status_code=404, detail="Share not found.")
    return {"status": "revoked", "id": share_id}


def _public_share(token: str) -> dict:
    share = get_share_by_token(token)
    if not share:
        raise HTTPException(status_code=404, detail="Share link expired or revoked.")
    return share


@app.get("/api/public-shares/{token}")
def get_public_share(token: str):
    share = _public_share(token)
    if share["resource_type"] == "collection":
        collection = next((item for item in list_source_sets() if item["id"] == share["resource_id"]), None)
        if not collection:
            raise HTTPException(status_code=404, detail="Shared collection no longer exists.")
        documents = [get_document(doc_id) for doc_id in collection["document_ids"]]
        resource = {"id": collection["id"], "name": collection["name"],
                    "documents": [{"id": doc["id"], "filename": doc["filename"], "tags": doc["tags"]}
                                  for doc in documents if doc and doc["status"] == "ready"],
                    "summary": summarize_evidence(collection["document_ids"])}
    else:
        conversation = next((item for item in get_all_conversations() if item["id"] == share["resource_id"]), None)
        if not conversation:
            raise HTTPException(status_code=404, detail="Shared conversation no longer exists.")
        resource = conversation
    return {"resource_type": share["resource_type"], "permission": share["permission"],
            "expires_at": share["expires_at"], "resource": resource,
            "comments": list_share_comments(share["id"])}


@app.post("/api/public-shares/{token}/comments")
def comment_on_share(token: str, request: ShareCommentRequest):
    share = _public_share(token)
    if share["permission"] != "comment":
        raise HTTPException(status_code=403, detail="This link is view-only.")
    try:
        return add_share_comment(share["id"], request.author, request.body)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


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


SUPPORTED_MIME = {
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "png": {"image/png"}, "jpg": {"image/jpeg"}, "jpeg": {"image/jpeg"},
    "webp": {"image/webp"}, "tiff": {"image/tiff"},
    "html": {"text/html"}, "htm": {"text/html"},
}


async def _save_and_validate_source(file: UploadFile, file_path: str, source_format: str) -> None:
    if source_format == "pdf":
        await _save_and_validate_pdf(file, file_path)
        return
    if source_format not in SUPPORTED_MIME or file.content_type not in SUPPORTED_MIME[source_format]:
        raise HTTPException(status_code=400, detail="Unsupported file type or MIME type.")
    total = 0
    try:
        with open(file_path, "wb") as destination:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File exceeds the upload limit.")
                destination.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
        if source_format in {"docx", "pptx", "xlsx"} and Path(file_path).read_bytes()[:2] != b"PK":
            raise HTTPException(status_code=400, detail="Invalid Office file signature.")
        if source_format in {"png", "jpg", "jpeg", "webp", "tiff"}:
            from PIL import Image
            with Image.open(file_path) as image:
                if image.width * image.height > 40_000_000:
                    raise HTTPException(status_code=413, detail="Image exceeds the 40 megapixel OCR limit.")
                image.verify()
    except HTTPException:
        Path(file_path).unlink(missing_ok=True)
        raise
    except Exception as exc:
        Path(file_path).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="File is malformed or unreadable.") from exc
    finally:
        await file.close()


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
            os.replace(file_path, os.path.join(QUARANTINE_DIR, f"{doc_id}{Path(file_path).suffix}.failed"))
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
    """Upload a supported source and stream step-by-step progress events."""
    filename = os.path.basename(file.filename or "")
    source_format = Path(filename).suffix.lower().lstrip(".")
    if source_format == "htm":
        source_format = "html"
    if source_format != "pdf" and source_format not in SUPPORTED_MIME:
        raise HTTPException(status_code=400, detail="Unsupported document format.")
    document_id = str(uuid.uuid4())
    storage_name = f"{document_id}.{source_format}"
    file_path = os.path.join(UPLOAD_DIR, storage_name)
    await _save_and_validate_source(file, file_path, source_format)
    add_document(
        filename,
        doc_id=document_id,
        storage_name=storage_name,
        status="processing",
    )
    set_source_format(document_id, source_format)

    async def event_generator():
        try:
            yield _sse({"step": 1, "label": "Extracting source content...", "status": "in_progress"})
            if source_format == "pdf":
                elements = await _run_ingestion_step(partition_documents, file_path)
                chunks = await _run_ingestion_step(create_chunks_by_title, elements)
                page_count = len((await asyncio.to_thread(PdfReader, file_path)).pages)
                report = _extraction_report(elements, page_count)
            else:
                chunks = await _run_ingestion_step(extract_sections, file_path, source_format)
                report = {"quality": "review_recommended" if source_format in {"png", "jpg", "jpeg", "webp", "tiff"} else "complete",
                          "warnings": ["OCR text should be checked against the image."] if source_format in {"png", "jpg", "jpeg", "webp", "tiff"} else [],
                          "section_count": len(chunks), "preview": [chunk.text[:500] for chunk in chunks[:5]]}
            set_document_extraction(document_id, report)

            yield _sse({"step": 2, "label": "Preparing sections and evidence...", "status": "in_progress"})

            yield _sse({"step": 3, "label": "Generating Multi-Modal AI Summaries...", "status": "in_progress"})
            documents = await _run_ingestion_step(
                build_documents, chunks, filename, document_id
            )
            for item in documents:
                item.metadata["source_format"] = source_format

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


def _extraction_report(elements, page_count: int) -> dict:
    page_text = {page: [] for page in range(1, page_count + 1)}
    unlocated = 0
    for element in elements:
        value = str(getattr(element, "text", "") or "").strip()
        page = getattr(getattr(element, "metadata", None), "page_number", None)
        if page in page_text:
            page_text[page].append(value)
        elif value:
            unlocated += 1
    missing = [page for page, parts in page_text.items() if len(" ".join(parts).strip()) < 25]
    warnings = []
    if missing:
        warnings.append(f"Little or no text was extracted from pages: {', '.join(map(str, missing[:20]))}.")
    if unlocated:
        warnings.append(f"{unlocated} text elements have no page location.")
    return {"quality": "review_recommended" if warnings else "complete", "warnings": warnings,
            "page_count": page_count, "low_text_pages": missing, "unlocated_elements": unlocated,
            "preview": [{"page": page, "text": " ".join(parts)[:500]} for page, parts in page_text.items()]}


def _fetch_public_web_page(url: str) -> tuple[str, bytes]:
    """Fetch one public HTML response with a DNS-pinned connection and no redirects."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Enter a public HTTP or HTTPS page URL.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("Only standard HTTP and HTTPS ports are supported.")
    addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    allowed = [entry[4][0] for entry in addresses if ipaddress.ip_address(entry[4][0]).is_global]
    if not allowed or len(allowed) != len(addresses):
        raise ValueError("The page address must resolve only to public IP addresses.")
    address = allowed[0]
    host = parts.hostname
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    if parts.scheme == "https":
        connection = http.client.HTTPSConnection(host, port, timeout=10)
        def connect():
            raw = socket.create_connection((address, port), timeout=10)
            connection.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
    else:
        connection = http.client.HTTPConnection(host, port, timeout=10)
        def connect():
            connection.sock = socket.create_connection((address, port), timeout=10)
    connection.connect = connect
    try:
        connection.request("GET", target, headers={"Host": host, "Accept": "text/html", "User-Agent": "MultiModalRAG/1.0"})
        response = connection.getresponse()
        if response.status != 200 or not response.getheader("content-type", "").lower().startswith("text/html"):
            raise ValueError("The URL must return a public HTML page (HTTP 200).")
        body = response.read(min(MAX_UPLOAD_BYTES, 2 * 1024 * 1024) + 1)
        if len(body) > min(MAX_UPLOAD_BYTES, 2 * 1024 * 1024):
            raise ValueError("Web page exceeds the 2 MB extraction limit.")
        return host, body
    finally:
        connection.close()


@app.post("/api/ingest-web-page")
async def ingest_web_page(request: WebPageRequest):
    try:
        host, body = await asyncio.to_thread(_fetch_public_web_page, request.url)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    file = UploadFile(file=io.BytesIO(body), filename=f"{host}.html", headers=Headers({"content-type": "text/html"}))
    return await ingest_document_stream(file)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.post("/api/chat")
def chat_query(request: QueryRequest):
    """Non-streaming query."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query string cannot be empty.")
    try:
        response_language(request.query, request.language)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        options = {"filters": request.filters} if request.filters and request.filters.active() else {}
        if request.mode == "compare":
            options["mode"] = "compare"
        if request.history:
            options["history"] = [message.model_dump() for message in request.history]
        if request.language != "auto":
            options["language"] = request.language
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
    try:
        response_language(request.query, request.language)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
            if request.mode == "compare":
                options["mode"] = "compare"
            if history:
                options["history"] = history
            if request.language != "auto":
                options["language"] = request.language
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


@app.delete("/api/conversations/{conversation_id}")
def remove_conversation(conversation_id: str):
    if not delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "deleted", "id": conversation_id}


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

@app.get("/api/folders")
def get_folders():
    return list_folders()


@app.post("/api/folders")
def save_folder(request: FolderRequest):
    try:
        return create_folder(request.name)
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            raise HTTPException(status_code=409, detail="Folder name already exists.") from exc
        raise


@app.put("/api/folders/{folder_id}")
def update_folder(folder_id: str, request: FolderRequest):
    try:
        found = rename_folder(folder_id, request.name)
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            raise HTTPException(status_code=409, detail="Folder name already exists.") from exc
        raise
    if not found:
        raise HTTPException(status_code=404, detail="Folder not found.")
    return {"id": folder_id, "name": request.name}


@app.delete("/api/folders/{folder_id}")
def remove_folder(folder_id: str):
    if not delete_folder(folder_id):
        raise HTTPException(status_code=404, detail="Folder not found.")
    return {"status": "deleted", "id": folder_id}


@app.patch("/api/documents/{doc_id}/folder")
def move_document(doc_id: str, request: MoveDocumentRequest):
    try:
        found = set_document_folder(doc_id, request.folder_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not found:
        raise HTTPException(status_code=404, detail="Ready document not found.")
    return get_document(doc_id)


@app.get("/api/documents/{doc_id}/extraction")
def get_extraction(doc_id: str):
    document = get_document(doc_id)
    if not document or document["status"] != "ready":
        raise HTTPException(status_code=404, detail="Ready document not found.")
    return {"report": document["extraction"], "review_status": document["review_status"], "review_note": document["review_note"]}


@app.patch("/api/documents/{doc_id}/extraction")
def review_extraction(doc_id: str, request: ExtractionReviewRequest):
    if not set_extraction_review(doc_id, request.status, request.note):
        raise HTTPException(status_code=404, detail="Ready document not found.")
    return get_extraction(doc_id)

@app.get("/api/source-sets")
def get_source_sets():
    return list_source_sets()


@app.post("/api/source-sets")
def save_source_set(request: SourceSetRequest):
    try:
        return create_source_set(request.name, request.document_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/source-sets/{source_set_id}")
def replace_source_set(source_set_id: str, request: SourceSetRequest):
    try:
        result = update_source_set(source_set_id, request.name, request.document_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Source set not found.")
    return result


@app.delete("/api/source-sets/{source_set_id}")
def remove_source_set(source_set_id: str):
    if not delete_source_set(source_set_id):
        raise HTTPException(status_code=404, detail="Source set not found.")
    return {"status": "deleted", "id": source_set_id}


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


@app.get("/api/documents/{doc_id}/file")
def get_document_file(doc_id: str):
    """Download a registered source, including non-PDF formats."""
    document = get_document(doc_id)
    if not document or document.get("status") != "ready":
        raise HTTPException(status_code=404, detail="Document not found.")
    storage_name = document.get("storage_name") or document["filename"]
    path = Path(UPLOAD_DIR) / storage_name
    if Path(storage_name).name != storage_name or path.resolve().parent != Path(UPLOAD_DIR).resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found.")
    return FileResponse(path, filename=document["filename"], content_disposition_type="attachment")


@app.get("/api/summaries")
def get_summary(scope: Literal["document", "section", "collection"], document_id: Optional[str] = None,
                source_set_id: Optional[str] = None, section_title: Optional[str] = None):
    if scope == "collection":
        selected = next((item for item in list_source_sets() if item["id"] == source_set_id), None)
        if not selected:
            raise HTTPException(status_code=404, detail="Source set not found.")
        ids = selected["document_ids"]
    else:
        document = get_document(document_id or "")
        if not document or document["status"] != "ready":
            raise HTTPException(status_code=404, detail="Ready document not found.")
        if scope == "section" and not section_title:
            raise HTTPException(status_code=422, detail="A section title is required.")
        ids = [document["id"]]
    return {"scope": scope, "summary": summarize_evidence(ids, section_title if scope == "section" else None)}


def _validated_output(request: OutputRequest) -> dict:
    if any(not (document := get_document(doc_id)) or document["status"] != "ready" for doc_id in request.document_ids):
        raise HTTPException(status_code=422, detail="Outputs require registered, ready documents.")
    return build_structured_output(request.kind, indexed_evidence(request.document_ids))


@app.post("/api/outputs")
def create_output(request: OutputRequest):
    return _validated_output(request)


@app.post("/api/outputs/report.md")
def export_output_report(request: OutputRequest):
    if request.kind != "report":
        raise HTTPException(status_code=422, detail="Only reports can be exported as Markdown.")
    result = _validated_output(request)
    return Response(content=result["markdown"], media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="source-report.md"'})


@app.delete("/api/documents/{doc_id}")
def remove_document(doc_id: str):
    """Delete a document's vectors, its registry row and the uploaded PDF."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    storage_name = doc.get("storage_name") or doc["filename"]
    file_path = os.path.join(UPLOAD_DIR, storage_name)
    quarantine_path = os.path.join(QUARANTINE_DIR, f"{doc_id}{Path(storage_name).suffix}.deleting")
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
