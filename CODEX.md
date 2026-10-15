# MultiModal RAG — Phase 1 Roadmap

Phase 1 stabilizes the existing MVP before retrieval and product features are expanded. Work is divided by impact on correctness and user safety.

## Part A — High priority: runtime reliability and safety

- [x] Fix all frontend lint errors and warnings that affect correctness.
- [ ] Move the frontend API base URL to validated environment configuration.
- [ ] Validate uploaded files by MIME type, PDF signature, size, and page count.
- [ ] Store uploads with generated document IDs so equal filenames cannot overwrite each other.
- [ ] Sanitize extracted table HTML before it is returned to or rendered by the frontend.
- [ ] Make ingestion and chat failures visible in the UI with retry actions.
- [ ] Add request timeouts and support cancelling uploads and streamed answers.
- [ ] Keep document, vector-store, and file deletion consistent when one operation fails.
- [ ] Remove or quarantine partially ingested data after a failed ingestion.

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

### Validation note

The Compose configuration, both Dockerfiles, and a full image build pass validation. The backend container reached healthy status and returned its expected health response; the frontend returned HTTP 200. Host port 3000 was already occupied during the final smoke test, so the configurable `FRONTEND_PORT` mapping was verified on port 3001.

## Recommended order

1. Finish the high-priority runtime work.
2. Add API integration coverage around the stabilized behavior.
3. Add frontend and end-to-end coverage.
4. Add CI and capture the final demo workflow.

