import os
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.rag_pipeline import process_and_store_documents, answer_query

app = FastAPI(
    title="Multi-Modal RAG API",
    description="Backend API for document ingestion and multi-modal query handling",
    version="1.0.0"
)

# Enable CORS for Next.js frontend running locally (port 3000)
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


@app.post("/api/ingest")
async def ingest_document(file: UploadFile = File(...)):
    """Upload PDF document and process vector ingestion pipeline"""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    # Save uploaded file to disk
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        process_and_store_documents(file_path)
        return {
            "status": "success",
            "message": f"Successfully ingested {file.filename}",
            "filename": file.filename
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")
