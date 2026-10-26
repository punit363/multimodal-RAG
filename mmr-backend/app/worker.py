"""Durable local ingestion worker; run separately from the API process."""

import argparse
import logging
import time
from pathlib import Path

from pypdf import PdfReader

from app import database, main


logger = logging.getLogger("rag_worker")


def process_job(job: dict) -> None:
    """Rebuild one source from its validated persisted original."""
    file_path = Path(main.UPLOAD_DIR) / job["storage_name"]
    if file_path.resolve().parent != Path(main.UPLOAD_DIR).resolve() or not file_path.is_file():
        raise FileNotFoundError("Registered source file is missing.")
    main.delete_document_vectors(job["document_id"])
    if job["source_format"] == "pdf":
        elements = main.partition_documents(str(file_path))
        chunks = main.create_chunks_by_title(elements)
        report = main._extraction_report(elements, len(PdfReader(str(file_path)).pages))
    else:
        chunks = main.extract_sections(str(file_path), job["source_format"])
        is_image = job["source_format"] in {"png", "jpg", "jpeg", "webp", "tiff"}
        report = {"quality": "review_recommended" if is_image else "complete",
                  "warnings": ["OCR text should be checked against the image."] if is_image else [],
                  "section_count": len(chunks), "preview": [chunk.text[:500] for chunk in chunks[:5]]}
    database.set_document_extraction(job["document_id"], report)
    documents = main.build_documents(chunks, job["filename"], job["document_id"])
    for item in documents:
        item.metadata["source_format"] = job["source_format"]
    main.store_documents(documents)
    database.update_document_status(job["document_id"], "ready")


def run_once(now: int | None = None) -> bool:
    """Claim one job, retry failures with backoff, and retain dead letters."""
    job = database.claim_ingestion_job(now=now)
    if not job:
        return False
    try:
        process_job(job)
    except Exception as exc:
        logger.error("Ingestion job failed: job_id=%s error_type=%s", job["id"], type(exc).__name__)
        result = database.fail_ingestion_job(job["id"], type(exc).__name__, now=now)
        if result["status"] == "dead":
            database.update_document_status(job["document_id"], "failed", "Worker attempts exhausted; review dead-letter job.")
    else:
        database.finish_ingestion_job(job["id"], now=now)
    return True


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Run durable ingestion jobs from the shared registry.")
    parser.add_argument("--once", action="store_true", help="Process one due job and exit")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.poll_seconds < 0.1:
        parser.error("Poll interval must be at least 0.1 seconds.")
    database.init_db()
    if args.once:
        run_once()
        return
    while True:
        if not run_once():
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main_cli()
