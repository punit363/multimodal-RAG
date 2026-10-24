# Local operations runbook

This is the Phase 5 Low-priority operational baseline for the current single-owner, SQLite/Chroma deployment. It does not establish production service-level targets or a backup/restore guarantee.

## Health and triage

- `GET /health/live` returns 200 when the API process can respond. It does not check storage.
- `GET /health/ready` returns 200 only when the SQLite document table is readable at the supported schema version and the upload and vector directories accept a temporary write. It returns 503 with `database`, `uploads`, and `vectors` marked `ok` or `failed` otherwise. No paths or file contents are returned.
- Docker Compose uses readiness for the backend health check. If it fails, inspect the failing check, container logs, the configured paths (`RAG_DATABASE_PATH`, `RAG_UPLOAD_DIR`, `RAG_VECTOR_DIR`), and volume permissions. Do not point the application at a new empty database while investigating missing data.
- A healthy readiness response does not prove OpenAI connectivity, model quality, vector-index integrity, or that every stored document can be opened.

Each API response carries `X-Request-ID`. The `rag_access` JSON log records `event`, `request_id`, `method`, route template, HTTP status, and duration to response headers. It does not record query strings, request bodies, or concrete share-token paths. The provided local and Docker startup commands disable Uvicorn's raw URL access log. Use the request ID and timestamp to match an error to the corresponding log record. Streaming duration covers response setup, not full token delivery. Limit access to logs because other application/library logs may still contain operational metadata.

If the browser reports an error, capture the response status and `X-Request-ID`, then inspect the matching backend log. For a 503 readiness result, fix the failing storage dependency first; for a 401 private API response, re-authenticate the owner session. If ingestion failed, inspect the document status and quarantine directory before retrying. Do not delete quarantine contents until the source has been recovered or safely re-ingested.

## SQLite schema checks

`init_db` upgrades legacy SQLite tables in place and records schema version 1 through `PRAGMA user_version`. Repeated startup is safe. A database with a higher version fails startup so an older application cannot silently write to a newer schema. Before deploying a new build, stop writes and preserve a consistent copy of SQLite, uploads, and Chroma together; migration and tested backup/restore automation are scheduled for the Medium priority. Verify the schema version with `sqlite3 "$RAG_DATABASE_PATH" 'PRAGMA user_version;'` where the CLI is installed. Never edit the version number by hand to bypass an incompatibility.

## Validation

Run `cd mmr-backend && ./venv/bin/python -m unittest discover -s tests -q`. The API tests cover readiness failure, liveness, request-ID redaction, and existing API behavior. The database tests cover repeat initialization, future-version rejection, and legacy migration. Run `docker compose config` to check Compose settings. A live Docker image rebuild and runtime smoke test remain a separate verification when the Docker daemon is available.
