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

## Phase 2 — Answer Grounding and Citations

**Status:** Complete — High and Medium priorities completed October 16, 2026; Low priority completed October 17, 2026.

**Objective:** Make answers easy to verify against precise locations in the uploaded PDFs. The original order was Low → Medium → High; the user directed High priority execution first on October 16, 2026, followed by Medium. The High priority implementation includes only the metadata and citation support it needs. Update the [Phase 2 engineering log](https://app.notion.com/p/3fa7cd5908fc81d0956ce0e18f7cad66) after each priority is complete.

### Low priority — evidence foundation and answer usability

- [x] Preserve document ID, stable chunk ID, page number or page range, element type, and available source location through partitioning, chunking, indexing, retrieval, and saved chat sources. Mark unavailable locations explicitly; do not invent page numbers.
- [x] Render generated answers as sanitized Markdown, including safe links and code blocks.
- [x] Add answer actions for copy, regenerate, and export; retain the existing cancel action as the stop control and make its state clear in the answer UI.

**Acceptance:** A retrieved source has stable identity and any real page/location metadata available from extraction; saved conversations retain it. Markdown and answer actions work for streamed and reloaded answers without unsafe rendering.

**Reviewable commits:** (1) evidence metadata and persistence, (2) Markdown rendering and answer controls, (3) focused tests/fixes if needed. Make each commit after its slice passes relevant checks; do not wait to commit the whole priority.

**Low priority completion:** New source chunks carry stable document/chunk IDs, actual extracted page numbers, element types, and complete/partial/unavailable page-location status through indexing, retrieval, and saved chat sources. Older vectors without this metadata display unavailable location. Answers render GitHub-flavored Markdown with raw HTML skipped, safe external links, code blocks, and source-bound citation buttons. Answer controls copy text, export Markdown with a source appendix, regenerate the original question as a new turn, and show an answer-level stop state during streaming. Validation: 21 backend tests, 9 component tests, 6 Chromium end-to-end tests, lint, webpack production build/TypeScript, production CSS check, production dependency audit (zero vulnerabilities), and `git diff --check` passed. Commits: `c66d4c9`, `139cbd8`, `14b6b66`, `56b810e`. Existing indexed PDFs need re-ingestion to gain new extraction metadata; Phase 3 will calibrate retrieval heuristics.

### Medium priority — visible grounding and feedback

- [x] Generate and render inline citations tied to returned source IDs, with document name and page label when known; make citations open the relevant source.
- [x] Expose retrieval relevance scores with a documented score meaning and label weak matches without presenting raw rank as confidence.
- [x] Add per-answer feedback and persist it so feedback remains after reloading a conversation.

**Acceptance:** Each cited answer span resolves to a returned source; unknown pages are labeled honestly. Weak matches are clearly identified. Feedback is saved and recoverable. Citation and feedback flows have automated coverage.

**Reviewable commits:** (1) citation contract and answer rendering, (2) score presentation and weak-match labels, (3) feedback persistence/UI and tests.

**Medium priority completion:** Citation markers link only to returned, registered PDF sources; unknown pages say "page unavailable," and unmatched markers display an unverified-source label. Source cards display normalized cosine retrieval similarity and mark scores below `0.50` as weak (the backend acceptance cutoff remains `0.35`). Helpful/not-helpful ratings are saved per assistant message in SQLite, can be cleared, and reload with conversations. Validation: 20 backend tests, 6 frontend component tests, 5 Chromium end-to-end tests, lint, TypeScript/webpack production build, production CSS check, and `git diff --check` passed. Commits: `492a8ed`, `ad0da00`, `3f826cb`. Low priority remains open; retrieval cutoff calibration is deferred to Phase 3.

### High priority — source inspection and unsupported-answer guardrails

- [x] Add a PDF viewer that opens the cited document at the cited page and highlights the cited content when reliable coordinates are available; use a page-level fallback when they are not.
- [x] Define and test a retrieval relevance threshold, then return an explicit insufficient-evidence response for unsupported questions in both streamed and non-streamed paths.
- [x] Add end-to-end coverage for navigation from an inline citation to the PDF and for low-relevance refusal.

**Acceptance:** A citation opens the correct document and page; highlighting never points to fabricated coordinates. Unsupported queries do not receive a speculative answer, and the UI explains insufficient evidence.

**Reviewable commits:** (1) document/page delivery and viewer, (2) highlight or page fallback, (3) refusal threshold and end-to-end tests.

**High priority completion:** Registered PDFs are served by ID. Extracted page numbers and valid pixel-space rectangles are stored with source chunks; the viewer highlights only valid rectangles and falls back to page navigation otherwise. Retrieved results are filtered by a configurable normalized cosine relevance threshold (default `0.35`); no supported result produces an explicit insufficient-evidence answer in both chat paths. Inline source markers open the cited PDF. Validation: 17 backend tests, 4 frontend component tests, 4 Chromium end-to-end tests, lint, production build/TypeScript, and production dependency audit passed. Commits: `4a97987`, `5045d56`, plus the completion-record commit below. The threshold is a heuristic pending the representative evaluation work planned for Phase 3.

### Execution record for every priority

After completing each priority, update the Phase 2 Notion page with implemented features, changed files, names of new or updated functions/classes, commit hashes, validation results, learnings, blockers, and next steps. Record names only for functions/classes, without copying implementation logic into Notion. Keep the project log's quick phase summary linked to the full Phase 2 page. These are planned slices; adjust commit boundaries when code review calls for smaller changes.

## Phase 3 — Retrieval Quality

**Status:** In progress — Low, Medium, and High features implemented October 21, 2026; representative quality evaluation deferred at the user's request.

**Objective:** Improve factual accuracy for difficult, follow-up, and cross-document questions. The [Phase 3 engineering log](https://app.notion.com/p/3fa7cd5908fc81eda42bfc938e72f64c) records evidence after each priority. Execute Low → Medium → High, using multiple reviewable commits within each priority.

### Low priority — measurement and controlled scope

- [ ] Add a fixed, versioned evaluation case format and repeatable retrieval/citation/answer-quality reporting. Record the Phase 2 baseline before tuning thresholds.
- [x] Add retrieval filters for selected documents, pages, dates, content types, and tags, with validation and honest handling of missing legacy metadata.

**Acceptance:** A representative dataset can measure recall, citation correctness, groundedness, and answer quality. Filtered queries return only matching evidence in both chat paths, and invalid filters fail clearly.

**Evaluation decision (October 21, 2026):** Skip the representative PDF quality baseline for now. Do not use the existing local PDFs as an evaluation corpus. Keep the evaluation task and its acceptance criteria open; the synthetic retrieval fixture is the only measurement so far.

### Medium priority — stronger retrieval and follow-up questions

- [x] Combine semantic and keyword retrieval, comparing its results with the fixed Phase 2 baseline on the synthetic fixture.
- [x] Rerank a bounded candidate set after initial retrieval and measure the effect on retrieval recall on the synthetic fixture. Citation correctness awaits a rated answer dataset.
- [x] Rewrite follow-up queries using bounded conversation context while retaining the original user question for answer generation.

**Acceptance:** Hybrid and reranked stages improve measured quality without regressing unsupported-answer behavior. Automated multi-turn tests cover resolved references and source isolation.

**Implementation and validation:** Document/page/date/type/tag filters and tag editing are wired through the API and chat UI. Hybrid retrieval uses BM25 candidate ranking, reciprocal-rank fusion, and a bounded diversity reranker; semantic-only and rewrite-disabled settings preserve a Phase 2 comparison mode. Follow-up retrieval uses at most six prior messages from the same conversation. The seven-chunk, six-question synthetic fixture measured recall@3 = 1.00 and abstention accuracy = 1.00 for semantic, hybrid, and reranked modes; recall@1 = 0.80 for all three. It showed no quality gain. The fixture bypasses PDF extraction and answer generation, so the representative baseline, citation correctness, groundedness, and answer quality are still unmeasured. Their evaluation is deferred at the user's request; Low and Medium quality acceptance remains open.

### High priority — document structure and synthesis

- [x] Add section- and page-aware hierarchical chunking with stable source and parent identities.
- [x] Index separate searchable representations for text, tables, and images while preserving citation links to the original PDF evidence.
- [x] Add an explicit cross-document comparison mode with cited claims from each compared document.

**Acceptance:** Cross-document and multimodal cases in the fixed evaluation set show a measurable improvement over the Phase 2 baseline; citations still resolve to real evidence. Automated tests cover ingestion, retrieval, and comparison.

**Implementation and validation:** PDF elements are chunked within page and title boundaries, with a stable section parent ID and separate text, table, and image-description vectors. Each representation keeps its own PDF page/location and original evidence for citation. Comparison mode requires two to four selected documents, retrieves evidence from each, and withholds answers that omit a registered citation from any selected document. Backend tests, frontend component checks, a Chromium comparison flow, lint, and the webpack production build pass. Existing PDFs must be re-ingested for the new index layout. Representative quality improvement remains unmeasured because that evaluation was deferred; High-priority acceptance is therefore still open. The implementation is recorded in separate backend, API/UI, and documentation commits.

### Execution record for every priority

After each priority, update the Phase 3 Notion page with implemented features, changed files, new and updated function/class names plus a short description of each, commits, validation results, learnings, blockers, and next steps. Update the main engineering log's quick phase summary with a link to the full Phase 3 details. Do not report a quality improvement until a representative evaluation has measured it.

## Phase 4 — Product Expansion

**Status:** Low, Medium, and High feature implementation complete October 24, 2026. Runtime multilingual OCR validation remains open because Docker was unavailable; representative language quality has not been measured.

**Objective:** Turn the PDF demo into a broader document-intelligence workspace. The [Phase 4 engineering log](https://app.notion.com/p/3fa7cd5908fc81d1b42bfa414f65d954) records progress after each priority. Execute Low → Medium → High with reviewable commits within each priority.

### Low priority — batch input and reusable scope

- [x] Upload multiple PDFs as a sequential batch with per-file progress, failure, cancellation, and retry while retaining the existing PDF validation and cleanup path.
- [x] Save selected documents as named source sets (collections), reload them for chat, update membership, and delete them. Keep source sets consistent when documents are removed. Existing document tags remain available.

**Acceptance:** A failed file does not stop other queued PDFs, each file has an actionable outcome, and selected documents can be restored from a saved source set after reload. Deleted documents cannot reappear through a source set.

**Low-priority implementation:** The file picker accepts multiple PDFs and processes them sequentially through the existing guarded ingestion stream. A batch lists each file's state and retries failed or cancelled files independently. Named source sets persist ready document IDs in SQLite, can be saved/loaded/updated/deleted in chat, and automatically lose membership when a document is deleted. Backend tests cover persistence, validation, API behavior, and deletion cleanup; Chromium tests cover batch continuation/retry and source-set reload/update/delete. The remaining Phase 4 features are scheduled in Medium and High priorities.

### Medium priority — organization, formats, and review

- [x] Add folders for organizing documents, plus document, section, and collection summaries.
- [x] Add DOCX, PPTX, XLSX, image, and web-page ingestion with format-specific extraction and retrieval fixtures.
- [x] Add scanned-PDF OCR quality checks and an extraction review workflow; make partial or uncertain extraction visible.

**Acceptance:** Every supported format has a verified ingestion and retrieval fixture. Users can review extraction quality, navigate folders, and inspect summaries at each supported level.

**Medium-priority implementation:** Folders persist in SQLite; documents can move between folders, and removing a folder leaves its documents unfiled. Document, section, and saved-set summaries expose bounded extractive text with chunk IDs. DOCX, PPTX, XLSX, image OCR, and uploaded or public-URL HTML sources pass through the existing ingest/index lifecycle; non-PDF sources can be downloaded by registered ID. Office ZIP extraction is bounded, image OCR is limited to 40 megapixels, and public URL fetching rejects private addresses, redirects, and oversized/non-HTML responses. PDF extraction reports flag pages with little extracted text or missing page locations; image OCR is marked for review. Reviewers can inspect excerpts and accept or flag an extraction. These are heuristic checks, not OCR confidence scores. Synthetic fixtures verify extraction-to-index text for each format; no representative user corpus was used. Validation: 62 backend tests, 9 frontend component tests, 12 Chromium end-to-end tests, lint, TypeScript, webpack production build, and Git whitespace checks passed. Backend and frontend implementation commits: `534187d`, `057d981`; documentation and additional fixture tests are in `ab3401e`; the image size guard is a separate follow-up commit. Next: High-priority structured outputs, multilingual support, and collaboration. Phase 3 representative quality evaluation remains deferred.

### High priority — advanced outputs and collaboration

- [x] Add structured extraction, timelines, comparison matrices, and exportable reports with source citations.
- [x] Add multilingual ingestion and question answering with language-aware validation.
- [x] Add shared collections, comments, and shareable conversations with explicit access controls.

**Acceptance:** Structured outputs and collaboration have end-to-end coverage; cited claims remain traceable to source evidence, and private APIs require an owner session when sharing is enabled. A share token grants only its selected collection or conversation and its view/comment permission. This is a single-owner workspace, not separate user accounts. Docker OCR runtime verification and representative multilingual answer quality remain open.

**High-priority implementation:** Structured extraction, timeline, comparison matrix, and Markdown report endpoints use bounded indexed evidence with source chunk IDs; matrix cells with no indexed evidence say unavailable. The chat UI creates these outputs and downloads reports. English, Hindi, Spanish, and French OCR packs are declared for the backend image; upload extraction uses configured OCR languages, and chat accepts a validated response language. Auto mode detects Hindi script and defaults other supported text to English. A configured owner key protects private APIs with a signed 24-hour cookie. The owner can create and revoke expiring, token-hashed links for collections or conversations with view or comment permission; a public share page shows scoped content and comments. Sharing is disabled without a strong owner key. Backend, frontend, and browser tests cover source identity, language validation, session access, share scope, permissions, expiry, revocation, and comments. The Next.js build reports an upstream security advisory. Docker was stopped during validation, so the multilingual OCR image was not rebuilt. Representative language and retrieval quality remain unmeasured.

### Execution record for every priority

After each priority, update the Phase 4 Notion page with implemented features, changed files, new and updated function/class names plus short descriptions, commits, validation results, learnings, blockers, and next steps. Update the main engineering log's quick phase summary with a link to the full Phase 4 details.

