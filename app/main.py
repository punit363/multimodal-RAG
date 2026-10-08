# app/main.py

import os
import shutil
import json
import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from app.rag_pipeline import answer_query_stream
from app.rag_pipeline import (
    partition_documents,
    create_chunks_by_title,
    separate_content_types,
    create_ai_enhanced_summary,
    process_and_store_documents,
    answer_query
)

app = FastAPI(title="Multi-Modal RAG API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "docs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class QueryRequest(BaseModel):
    query: str
    top_k: int = 3

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Multi-Modal RAG API is running"}

@app.post("/api/ingest-stream")
async def ingest_document_stream(file: UploadFile = File(...)):
    """Upload PDF document and stream step-by-step progress events"""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    async def event_generator():
        try:
            # Step 1: Document Partitioning
            yield f"data: {json.dumps({'step': 1, 'label': 'Partitioning PDF Layout...', 'status': 'in_progress'})}\n\n"
            await asyncio.sleep(0.5)
            elements = partition_documents(file_path)

            # Step 2: Content Categorization & Vision Extraction
            yield f"data: {json.dumps({'step': 2, 'label': 'Extracting Text, Tables & Images...', 'status': 'in_progress'})}\n\n"
            await asyncio.sleep(0.5)
            chunks = create_chunks_by_title(elements)

            # Step 3: AI Vision Summaries
            yield f"data: {json.dumps({'step': 3, 'label': 'Generating Multi-Modal AI Summaries...', 'status': 'in_progress'})}\n\n"
            await asyncio.sleep(0.5)
            
            # Step 4: Vector Store Persistence
            yield f"data: {json.dumps({'step': 4, 'label': 'Generating Embeddings & Storing in ChromaDB...', 'status': 'in_progress'})}\n\n"
            process_and_store_documents(file_path)

            yield f"data: {json.dumps({'step': 5, 'label': 'Document Indexing Complete!', 'status': 'completed', 'filename': file.filename})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'step': -1, 'label': f'Error: {str(e)}', 'status': 'error'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/chat")
def chat_query(request: QueryRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query string cannot be empty.")
    try:
        return answer_query(request.query, k=request.top_k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {str(e)}")
    
@app.post("/api/chat-stream")
def chat_query_stream(request: QueryRequest):
    """Query ChromaDB and stream LLM response tokens via Server-Sent Events (SSE)"""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query string cannot be empty.")

    return StreamingResponse(
        answer_query_stream(request.query, k=request.top_k),
        media_type="text/event-stream"
    )