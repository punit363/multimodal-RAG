# MultiModal RAG — Phase 1 Roadmap

Phase 1 stabilizes the existing MVP before retrieval and product features are expanded. Work is divided by impact on correctness and user safety.

**Status:** Complete — October 16, 2026

## Part A — High priority: runtime reliability and safety

- [x] Fix all frontend lint errors and warnings that affect correctness.
- [x] Move the frontend API base URL to validated environment configuration.
- [x] Validate uploaded files by MIME type, PDF signature, size, and page count.
- [x] Store uploads with generated document IDs so equal filenames cannot overwrite each other.
- [x] Sanitize extracted table HTML before it is returned to or rendered by the frontend.
- [x] Make ingestion and chat failures visible in the UI with retry actions.
- [x] Add request timeouts and support cancelling uploads and streamed answers.
- [x] Keep document, vector-store, and file deletion consistent when one operation fails.
- [x] Remove or quarantine partially ingested data after a failed ingestion.

### Completion criteria

- `npm run lint` and `npm run build` pass.
- Invalid, oversized, and malformed PDFs are rejected with clear messages.
- Re-uploading two files with the same display name does not overwrite either file.
- Document-derived HTML cannot execute scripts in the browser.
- Interrupted ingestion and chat requests leave recoverable, consistent state.

## Part B — Lower priority: maintainability and delivery

- [x] Add a project-level README with architecture, setup, environment, and validation instructions.
- [x] Add a safe backend example environment file without real credentials.
- [x] Add Dockerfiles and a Compose configuration for running both services.
- [x] Add a focused backend database test suite using an isolated temporary database.
- [x] Add API integration tests for conversations, documents, ingestion validation, and retrieval filters.
- [x] Add frontend component and end-to-end tests for source selection, streaming, citations, and ingestion progress states.
- [x] Add continuous integration for lint, build, and tests.
- [x] Add screenshots and a short demo workflow to the documentation.

### Completion criteria

- A new contributor can configure and run both services from the README.
- `docker compose up --build` starts the frontend and backend.
- Tests never read or modify the developer's local databases or uploaded documents.
- Pull requests automatically run lint, build, and test checks once CI is added.

## Final validation

- Backend: 13 tests passed, covering API behavior, upload validation, duplicate filenames, failure cleanup, deletion recovery, sanitization, and database migration.
- Frontend: 3 component tests and 2 Chromium end-to-end tests passed.
- Quality: frontend lint, production build, TypeScript checks, Python compilation, and `git diff --check` passed.
- Packaging: both Docker images rebuilt successfully; the backend reported healthy and returned its expected health response, while the frontend returned HTTP 200.
- Environment: host port 3000 was occupied, so the configurable `FRONTEND_PORT` mapping was verified on port 3001.

## Phase handoff

Phase 1 is complete. Phase 2 can build on this stable baseline with stronger retrieval quality, grounded citations, evaluation datasets, and retrieval observability.

