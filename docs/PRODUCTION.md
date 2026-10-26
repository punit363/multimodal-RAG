# Phase 5 High deployment and migration

This release supports **one workspace per deployed stack**. Each workspace needs its own PostgreSQL database, Docker Compose project/vector volume, owner key, and S3 prefix. The database and vector directory record their workspace ID and reject reuse under another ID. Member keys grant `owner`, `editor`, or `viewer` access within that stack; only the owner can create/revoke members or manage shares and operations endpoints. Public shares remain capability links with expiry. This is an isolated-stack model, not a horizontally scaled tenant router.

## Configuration and secrets

Copy [`deploy/example.env`](../deploy/example.env) to an ignored environment file and replace every placeholder. Set the public API URL and frontend origin to HTTPS addresses served by a reverse proxy. The Compose ports bind to loopback; the proxy and TLS termination belong to the host. Keep `MMD_WORKSPACE_ID` unique and begin `MMD_ORIGINALS_PREFIX` with that ID. Never reuse the database, vector volume, owner key, or object prefix for another workspace.

Provision the three secret files outside the repository from the host's secret manager: `MMD_OWNER_KEY_FILE` (at least 32 random characters), `MMD_DATABASE_URL_FILE` (PostgreSQL URL), and `MMD_OPENAI_KEY_FILE`. The backend accepts `*_FILE` for these secrets and for AWS credentials. An AWS deployment can instead set `RAG_SECRETS_MANAGER_ID` to a JSON secret containing allowlisted keys such as `OPENAI_API_KEY`, `RAG_OWNER_API_KEY`, and `RAG_DATABASE_URL`; the runtime fetches it through workload identity before loading app settings. Do not set both sources for the same key. The S3 client uses the usual AWS credential chain, so a workload identity is preferred to long-lived access keys. A bucket with versioning, encryption, and restricted IAM permissions should be prepared before cutover. Production startup rejects a weak owner key, non-PostgreSQL metadata, missing object bucket, default workspace ID, non-HTTPS CORS origin, insecure cookies, or inline ingestion.

The single Chroma volume is mounted by one API and one worker. Treat it as a persistent service volume, snapshot it with writes stopped, and avoid adding replicas without moving Chroma to a dedicated server. The upload directories are temporary; object storage is authoritative after a successful upload. The PDF/file endpoints download and verify each original before responding.

## Migrate an existing local workspace

1. Stop the old API and worker. Create and verify the existing [offline backup](OPERATIONS.md) before touching data. Keep the backup and original volumes until post-cutover checks pass.
2. Run the current application once against a copy of the old SQLite database to upgrade it to schema version 5. Use the same `RAG_WORKSPACE_ID` planned for the new stack; the migration binds the database to that workspace. Upgrade on a copy so the old deployment stays recoverable.
3. Create an empty PostgreSQL database dedicated to that workspace. With `RAG_WORKSPACE_ID` and `RAG_DATABASE_URL` set, run `python -m scripts.migrate_sqlite_to_postgres --sqlite /path/to/copied/rag_history.db`. This verifies the source schema/integrity, refuses a nonempty target, copies all registry tables in one transaction, and checks row counts.
4. Set the same PostgreSQL URL and the workspace's `RAG_ORIGINALS_BUCKET`/`RAG_ORIGINALS_PREFIX`. Run `python -m scripts.migrate_originals_to_s3 --uploads /path/to/old/docs`. Each registered original is uploaded with SHA-256 metadata and checked with `HeadObject`; local originals remain for rollback. Re-running an interrupted copy is safe.
5. Copy the stopped Chroma directory into the new stack's dedicated vector volume. Keep the workspace marker with the directory, or let the new startup create it only when the volume contains data from the same workspace.
6. Start the new stack, run the acceptance checks below, then switch the HTTPS proxy. Keep the old stack stopped and retain the backup until recovery has been exercised.

If the source SQLite database is older than schema 5, do not run the direct copy script against it. The copy of the old database must be upgraded first. The PostgreSQL schema initializes at version 5 and upgrades existing version 3/4 PostgreSQL registries without deleting rows. A newer unsupported schema fails startup.

## Build, deploy, and roll back

`python3 deploy/release.py --env-file /path/to/staging.env --validate-only` checks the environment and Compose interpolation without changing the stack. `python3 deploy/release.py --env-file /path/to/staging.env` builds Git-SHA-tagged backend/frontend images, deploys them to a workspace-specific Compose project, waits for healthy services, and runs the HTTP smoke checks. If a previously healthy release exists and health/smoke fails, it automatically restores the prior image tags. `--rollback` selects the recorded previous tags manually. The state file under `.deploy-state/` holds image tags only, not secrets.

Run `docker compose --env-file /path/to/staging.env -f deploy/compose.yml -p mmdrag-staging-WORKSPACE ps` to inspect the stack. Keep a verified PostgreSQL/S3/vector snapshot before each schema-changing release. Image rollback is safe only while the previous image supports the active schema; database/object/vector recovery uses a separate snapshot and a restored isolated stack.

## Acceptance targets

The release's smoke check requires readiness, rejects unauthenticated document listing, logs in as owner, and lists documents. After staging is reachable, run `python3 deploy/acceptance.py --api https://api.staging.example.com --owner-key-file /path/to/owner-key --load-requests 100 --max-p95-ms 1000 --other-api https://api.other-workspace.example.com --pdf /path/to/safe-sample.pdf`. The load check is a bounded liveness probe rather than an AI throughput benchmark; the cross-workspace check sends the first workspace's session to the second and expects a 401. The optional PDF check ingests, verifies the original, queries the document, and deletes the temporary document.

For recovery, restore PostgreSQL, the S3 object prefix, and the Chroma volume into an isolated stack using the same workspace ID and owner key. Add `--recovered-api https://api.restored.example.com` to compare document IDs, original checksums, and vector-backed summaries with the source. Record the recovery time and any data loss against the team's agreed RTO/RPO. Neither a live target nor RTO/RPO has been supplied for this repository yet, so these acceptance commands are available but have not been run against a hosted environment.
