# AGENTS.md

## State of the repo

Phase 1 shipped: capture pipeline (text + doc upload) + SQLite/FTS5 + basic RAG chat, per PLAN.md §4. `PLAN.md` remains the source of truth for scope (v0.1, all decisions resolved) — Phases 2–4 (vector, graph, voice, guardrails) are unbuilt.

## Non-obvious facts that constrain all code

- **Repo layout:** `backend/` (FastAPI, uv-managed venv) + `frontend/` (Next.js 16, App Router). Run backend with `uv run uvicorn app.main:app --reload` from `backend/` (never bare `uvicorn` — deps live in `.venv`); frontend with `npm run dev` from `frontend/`. Tests: `uv run pytest tests` from `backend/`.
- **All models run via local Ollama — localhost-only invariant (hard constraint):** no hosted APIs, no API keys, no telemetry. `OLLAMA_HOST` must stay `http://localhost:11434`. Documents/audio never leave the machine; uvicorn binds 127.0.0.1 and CORS allows only localhost:3000.
- **Model picks (16GB Mac tier):** chat/answers `qwen3:8b` (Q4); embeddings `nomic-embed-text` (Phase 2); OCR `qwen-ocr:small` variant (Phase 4). Override chat model via `OLLAMA_MODEL` env (e.g. `hermes3` is still installed). qwen3 chat must send `"think": false` + low temperature (set in `app/retrieval/chat.py`).
- **Backend internals (Phase 1):** raw `sqlite3` stdlib (no ORM); `app/db.py` `get_conn()` per-operation connections, schema applied at startup from `app/schema.sql`; ingestion is FastAPI `BackgroundTasks` (status queued→processing→indexed/failed); FTS5 is a standalone table `captures_fts` (rowid = captures.id), synced manually by the pipeline — always delete+reinsert on edit.
- **Config is env-driven at import time:** `app/config.py` reads `NOTE_MASTER_DATA_DIR`, `OLLAMA_MODEL`, etc. when imported — tests set env before importing app. Runtime data lives in `backend/data/` (gitignored).
- **Versioning + cascade:** re-uploaded docs create a new `captures` row sharing `document_group_id` (version bump, `is_latest` flip); deletion must cascade to FTS rows + files. Partial unique index enforces one latest per group.
- **Testing quirks:** TestClient runs BackgroundTasks after the response, so the create response is `queued` — tests poll `GET /captures/{id}` until indexed. Chat tests need Ollama running with the configured model.
- **OCR routing at ingestion:** cheap file-type/content check — docs with a real text layer (Word, Excel, text PDFs) → local extraction (pypdf/python-docx/openpyxl, no model); scanned/photographed docs (Aadhar, PAN, receipts) → Qwen-OCR (Phase 4 — stub currently raises, ingestion marks capture `failed`).

## Stack (PLAN.md §3.5, §3.7 — all decisions resolved, do not reopen)

- **Frontend:** Next.js (responsive web; no native app in v1).
- **Backend:** FastAPI, orchestrating ingestion pipeline + retrieval engine + guardrail layer.
- **Storage is two embedded engines, no standalone services:** one SQLite file holds app state + FTS5 + vectors via sqlite-vec; a second embedded store is LadybugDB (property graph, MIT). Files (audio, uploads) go on disk referenced by path — never blobbing into SQLite.
- **ASR:** `faster-whisper` (CTranslate2), `small`/`base` model, CPU, run on-demand per voice note — not a persistent background process.
- **User model:** single-user v1 — no auth/tenant isolation; `user_id` scoping deferred. Keep a `users` table anyway (future-proofing, §3.2a).
- **Sensitivity tiers (`none`/`moderate`/`high`)** are assigned at ingestion, not a boolean flag; only `high` (ID/financial docs) is PIN-gated at retrieval, others get a warning label. The PIN is a local app-level passcode (not tied to any auth system) with its own set/change/recovery flow.
- **Retrieval is hybrid** (graph traversal + vector + FTS5 fused/reranked) with strict RAG grounding — answers must come only from retrieved context, with an explicit "not found" path, and every sensitive retrieval is audit-logged.
- **Suggested phasing** (§4): build in order — Phase 1 capture pipeline + SQLite/FTS5 + basic chat, then vector, then graph, then voice + guardrail hardening.
