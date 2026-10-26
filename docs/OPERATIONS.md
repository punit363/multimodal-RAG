# Local operations runbook

This is the Phase 5 Low/Medium operational baseline for the current single-owner, SQLite/Chroma deployment. It does not establish production service-level targets or multi-user isolation.

## Health and triage

- `GET /health/live` returns 200 when the API process can respond. It does not check storage.
- `GET /health/ready` returns 200 only when the SQLite document table is readable at the supported schema version and the upload and vector directories accept a temporary write. It returns 503 with `database`, `uploads`, and `vectors` marked `ok` or `failed` otherwise. No paths or file contents are returned.
- Docker Compose uses readiness for the backend health check. If it fails, inspect the failing check, container logs, the configured paths (`RAG_DATABASE_PATH`, `RAG_UPLOAD_DIR`, `RAG_VECTOR_DIR`), and volume permissions. Do not point the application at a new empty database while investigating missing data.
- A healthy readiness response does not prove OpenAI connectivity, model quality, vector-index integrity, or that every stored document can be opened.

Each API response carries `X-Request-ID`. The `rag_access` JSON log records `event`, `request_id`, `method`, route template, HTTP status, and duration to response headers. It does not record query strings, request bodies, or concrete share-token paths. The provided local and Docker startup commands disable Uvicorn's raw URL access log. Use the request ID and timestamp to match an error to the corresponding log record. Streaming duration covers response setup, not full token delivery. Limit access to logs because other application/library logs may still contain operational metadata.

If the browser reports an error, capture the response status and `X-Request-ID`, then inspect the matching backend log. For a 503 readiness result, fix the failing storage dependency first; for a 401 private API response, re-authenticate the owner session. If ingestion failed, inspect the document status and quarantine directory before retrying. Do not delete quarantine contents until the source has been recovered or safely re-ingested.

## SQLite schema checks

`init_db` upgrades legacy SQLite tables in place and records schema version 2 through `PRAGMA user_version`. Repeated startup is safe. Version 1 adds operational usage and audit tables during the 1→2 migration. A database with a higher version fails startup so an older application cannot silently write to a newer schema. Before deploying a new build, stop the backend and create a verified backup. Start the new build on an isolated restored copy first, check readiness and documents, then migrate the live deployment. Verify the schema version with `sqlite3 "$RAG_DATABASE_PATH" 'PRAGMA user_version;'` where the CLI is installed. Never edit the version number by hand to bypass an incompatibility. Keep the original backup until the upgraded deployment is verified; a backup must be restored with an application version that understands its schema.

## Usage controls and audit

The local backend applies SQLite-backed fixed-minute and daily windows to login, chat, ingestion, outputs, sharing, public views, and comments. Default chat limits are 30/minute and 1,000/day; ingestion limits are 10/minute and 100/day. `RAG_RATE_<GROUP>` and `RAG_DAILY_QUOTA_<GROUP>` override a group's limits, and `RAG_MAX_DOCUMENTS` defaults to 500 active documents. Limit rejections return 429; rate-window rejections include `Retry-After`. Counters are shared through SQLite. This is a single-owner budget guard, not per-tenant billing or distributed rate limiting. A public comment or view can consume its shared route budget. The document cap is enforced at registry insertion as well as at request admission.

`GET /api/audit-events` lists the latest 100 fixed-action records for the owner. Records contain action, outcome, request ID, and timestamp; they omit prompts, names, file contents, IP addresses, and link tokens. An `allowed` chat or ingestion event means the request was admitted, not that a later stream completed. Audit writes are best-effort and are not a compliance-grade ledger. With `RAG_OWNER_API_KEY` set, private operations, audit, metrics, and dashboard routes require the owner session.

## Retention and deletion

Uploaded originals and vectors remain until explicit document deletion; conversations remain until `DELETE /api/conversations/{id}`, which also removes its messages, links, and comments. The existing document delete path removes its original and vectors with quarantine/recovery behavior. Quarantine files require manual review before deletion. Expired share links immediately fail authorization, and the cleanup command removes their rows and comments. Audit events are retained 90 days by default; usage windows are retained two days. Run from `mmr-backend` with the correct database path:

```bash
python -m scripts.retention --database rag_history.db
python -m scripts.retention --database rag_history.db --apply
```

The first command is a dry run and reports counts. Inspect those counts before `--apply`; schedule the apply command with an operator-managed scheduler if ongoing cleanup is needed. Neither command reads or modifies document contents or vectors.

## Offline backup and isolated restore

Stop the backend and all writers to SQLite, uploads, and Chroma before `create` or `restore`. The command requires `--offline-confirmed` as an explicit operational guard. Run from `mmr-backend` and put archives outside the source directories:

```bash
python -m scripts.backup create --database rag_history.db --uploads docs --vectors db/chroma_db --archive ../rag-backup.zip --offline-confirmed
python -m scripts.backup verify --archive ../rag-backup.zip
python -m scripts.backup restore --archive ../rag-backup.zip --destination ../rag-restore-check --offline-confirmed
```

For Docker volume paths, use `/app/data/rag_history.db`, `/app/docs`, and `/app/db/chroma_db` inside an isolated container with those volumes mounted, and mount a separate backup destination. The backend image includes the backup script. The archive includes a SQLite backup snapshot and every regular upload/vector file, with SHA-256 checksums. Verification checks the exact member list, SQLite integrity/schema, and the presence of all ready registered originals. Restore refuses an existing destination and reconstructs `data/`, `docs/`, and `db/chroma_db/` only after verification. Start an application pointed at the isolated restore and check readiness, document downloads, and representative retrieval before replacing any live state. The archive is **not encrypted**; protect its access and storage. It detects corruption, not malicious replacement or live-write inconsistency. Automated disaster recovery and managed storage are still Phase 5 High work.

## Metrics, traces, and errors

`GET /api/ops/metrics` exposes bounded in-process counts by route template and HTTP status class, latency buckets, named span counts, and up to 25 recent 5xx summaries. `GET /api/ops/dashboard` shows the same data in a small auto-refreshing page. `X-Trace-ID` matches `X-Request-ID`, and `Server-Timing` reports time to response headers. Named spans cover non-streaming chat answers, public-page fetch, and structured output creation. Streaming token delivery and background extraction are not yet traced end to end. Metrics reset on process restart and are not aggregated across workers. Error summaries contain request ID, route template, status, and type without exception messages or user content. Protect owner sessions and logs; external telemetry retention, alerting, and service targets remain future deployment work.

## Validation

Run `cd mmr-backend && ./venv/bin/python -m unittest discover -s tests -q`. The suite covers readiness, privacy-safe logs, quotas, audit, retention, SQLite migration, isolated backup/restore, metrics, trace IDs, and existing API behavior. Run `docker compose config` to check Compose settings. A live Docker image rebuild and runtime smoke test remain a separate verification when the Docker daemon is available.
