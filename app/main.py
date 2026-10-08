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
